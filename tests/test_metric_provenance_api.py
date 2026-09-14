"""Integration tests for Backend API Metric Provenance and Price Integrity (Requirement R1).

Verifies that:
1. Endpoints (/api/elite/risk_metrics, /api/portfolio, /api/positions) adhere to MetricProvenanceAgent.
2. Unapproved metrics return value: null with verification_status: "unavailable".
3. Valid independent approvals allow metrics to publish with verification_status: "verified".
4. Tampered sources or self-approvals immediately fail closed to "unavailable".
5. Silent entry_price fallback in compute_current_equity and system_emergency_stop is eliminated.
6. No synthetic balances (e.g. R$ 1.000.000) are emitted.
7. Candle integrity rejection (HTTP 502/503) remains strictly preserved.
8. MetricIdentity: approval for one metric name does not approve another.
"""
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.data import database
from trading_bot.data.metric_provenance import MetricProvenanceAgent, MetricRecord, metric_digest


@pytest.fixture
def test_app():
    app = FastAPI()
    app.get("/api/elite/risk_metrics")(main.get_risk_metrics_route)
    app.get("/api/portfolio")(main.api_get_portfolio)
    app.get("/api/positions")(main.get_positions_route)
    app.get("/api/candles/{ticker}")(main.get_candles)
    return app


@pytest.fixture
def clean_db(tmp_path, monkeypatch):
    db_file = tmp_path / "trading_bot.db"
    original_db = database.DB_PATH
    database.DB_PATH = str(db_file)
    database.init_db()

    fixed_time = datetime.datetime(2026, 9, 14, 10, 0, 0, tzinfo=datetime.timezone.utc)
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, exit_price, target_price, stop_loss, entry_date, exit_date, pnl_pct, status) "
        "VALUES ('PETR4.SA', 'BUY', 10.0, 30.0, 33.0, 35.0, 28.0, ?, ?, 10.0, 'closed')",
        (fixed_time.isoformat(), fixed_time.isoformat()),
    )
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, exit_price, target_price, stop_loss, entry_date, exit_date, pnl_pct, status) "
        "VALUES ('VALE3.SA', 'BUY', 5.0, 60.0, 57.0, 70.0, 55.0, ?, ?, -5.0, 'closed')",
        (fixed_time.isoformat(), fixed_time.isoformat()),
    )
    conn.commit()
    conn.close()

    yield db_file
    database.DB_PATH = original_db


@pytest.fixture
def empty_registry(tmp_path, monkeypatch):
    registry = tmp_path / "metric_approvals.json"
    registry.write_text(json.dumps({"version": 1, "approvals": []}), encoding="utf-8")
    monkeypatch.setenv("METRIC_APPROVALS_PATH", str(registry))
    return registry


def test_unapproved_risk_metrics_returns_unavailable_and_null(test_app, clean_db, empty_registry):
    client = TestClient(test_app)
    response = client.get("/api/elite/risk_metrics")
    assert response.status_code == 200
    data = response.json()

    assert data["verification_status"] == "unavailable"
    assert data["value"] is None
    assert data["win_rate"] is None
    assert data["avg_win"] is None
    assert data["avg_loss"] is None
    assert data["sharpe"] is None
    assert data["sortino"] is None
    assert data["calmar"] is None
    assert data["max_drawdown_pct"] is None
    assert data["var_95_daily"] is None

    prov = data["metrics_provenance"]["win_rate"]
    assert prov["verification_status"] == "unavailable"
    assert prov["value"] is None
    assert prov["reason"] == "independent_approval_required"


def test_approved_risk_metric_publishes_verified(test_app, clean_db, tmp_path, monkeypatch):
    registry = tmp_path / "approved_metrics.json"
    monkeypatch.setenv("METRIC_APPROVALS_PATH", str(registry))

    rel_db = database.PROJECT_ROOT / "data" / "test_provenance.db"
    rel_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(clean_db, rel_db)

    original_db = database.DB_PATH
    database.DB_PATH = str(rel_db)

    try:
        fixed_time = datetime.datetime(2026, 9, 14, 10, 0, 0, tzinfo=datetime.timezone.utc)
        source_ref = str(rel_db.resolve().relative_to(database.PROJECT_ROOT.resolve())).replace("\\", "/")
        source_sha256 = hashlib.sha256(rel_db.read_bytes()).hexdigest()

        record = MetricRecord(
            metric_name="win_rate",
            value=0.5,
            unit="fraction",
            source_ref=source_ref,
            source_sha256=source_sha256,
            observed_at=fixed_time,
            collected_at=fixed_time,
            computed_at=fixed_time,
            owner="backend.app.data.database.get_risk_metrics",
            method_version="1.0",
            verification_status="unverified",
        )

        approval = {
            "metric_name": "win_rate",
            "metric_sha256": metric_digest(record),
            "reviewed_by": "independent_risk_auditor",
            "reviewed_at": (fixed_time + datetime.timedelta(hours=1)).isoformat(),
            "status": "approved",
        }
        registry.write_text(json.dumps({"version": 1, "approvals": [approval]}), encoding="utf-8")

        client = TestClient(test_app)
        # Consumes real evidence timestamp from database directly without mocking datetime.now!
        response = client.get("/api/elite/risk_metrics")

        assert response.status_code == 200
        data = response.json()
        assert data["win_rate"] == 0.5
        assert data["metrics_provenance"]["win_rate"]["verification_status"] == "verified"
        assert data["metrics_provenance"]["win_rate"]["value"] == 0.5
    finally:
        database.DB_PATH = original_db
        if rel_db.exists():
            rel_db.unlink()


def test_metric_identity_approval_does_not_transfer_to_different_metric(test_app, clean_db, tmp_path, monkeypatch):
    registry = tmp_path / "approved_metrics.json"
    monkeypatch.setenv("METRIC_APPROVALS_PATH", str(registry))

    rel_db = database.PROJECT_ROOT / "data" / "test_identity.db"
    rel_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(clean_db, rel_db)

    original_db = database.DB_PATH
    database.DB_PATH = str(rel_db)

    try:
        fixed_time = datetime.datetime(2026, 9, 14, 10, 0, 0, tzinfo=datetime.timezone.utc)
        source_ref = str(rel_db.resolve().relative_to(database.PROJECT_ROOT.resolve())).replace("\\", "/")
        source_sha256 = hashlib.sha256(rel_db.read_bytes()).hexdigest()

        # Approval is ONLY for win_rate
        record_win_rate = MetricRecord(
            metric_name="win_rate",
            value=0.5,
            unit="fraction",
            source_ref=source_ref,
            source_sha256=source_sha256,
            observed_at=fixed_time,
            collected_at=fixed_time,
            computed_at=fixed_time,
            owner="backend.app.data.database.get_risk_metrics",
            method_version="1.0",
            verification_status="unverified",
        )

        approval = {
            "metric_name": "win_rate",
            "metric_sha256": metric_digest(record_win_rate),
            "reviewed_by": "independent_risk_auditor",
            "reviewed_at": (fixed_time + datetime.timedelta(hours=1)).isoformat(),
            "status": "approved",
        }
        registry.write_text(json.dumps({"version": 1, "approvals": [approval]}), encoding="utf-8")

        client = TestClient(test_app)
        response = client.get("/api/elite/risk_metrics")

        assert response.status_code == 200
        data = response.json()
        assert data["win_rate"] == 0.5
        assert data["metrics_provenance"]["win_rate"]["verification_status"] == "verified"
        # avg_win was NOT approved and MUST remain unavailable!
        assert data["avg_win"] is None
        assert data["metrics_provenance"]["avg_win"]["verification_status"] == "unavailable"
    finally:
        database.DB_PATH = original_db
        if rel_db.exists():
            rel_db.unlink()


def test_tampered_source_blocks_approved_metric(test_app, clean_db, tmp_path, monkeypatch):
    registry = tmp_path / "approved_metrics.json"
    monkeypatch.setenv("METRIC_APPROVALS_PATH", str(registry))

    rel_db = database.PROJECT_ROOT / "data" / "test_tamper.db"
    rel_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(clean_db, rel_db)

    original_db = database.DB_PATH
    database.DB_PATH = str(rel_db)

    try:
        fixed_time = datetime.datetime(2026, 9, 14, 10, 0, 0, tzinfo=datetime.timezone.utc)
        source_ref = str(rel_db.resolve().relative_to(database.PROJECT_ROOT.resolve())).replace("\\", "/")
        source_sha256 = hashlib.sha256(rel_db.read_bytes()).hexdigest()

        record = MetricRecord(
            metric_name="win_rate",
            value=0.5,
            unit="fraction",
            source_ref=source_ref,
            source_sha256=source_sha256,
            observed_at=fixed_time,
            collected_at=fixed_time,
            computed_at=fixed_time,
            owner="backend.app.data.database.get_risk_metrics",
            method_version="1.0",
            verification_status="unverified",
        )

        approval = {
            "metric_name": "win_rate",
            "metric_sha256": metric_digest(record),
            "reviewed_by": "independent_risk_auditor",
            "reviewed_at": (fixed_time + datetime.timedelta(hours=1)).isoformat(),
            "status": "approved",
        }
        registry.write_text(json.dumps({"version": 1, "approvals": [approval]}), encoding="utf-8")

        with open(rel_db, "ab") as f:
            f.write(b"tampered_bytes")

        client = TestClient(test_app)
        response = client.get("/api/elite/risk_metrics")

        assert response.status_code == 200
        data = response.json()
        assert data["win_rate"] is None
        assert data["metrics_provenance"]["win_rate"]["verification_status"] == "unavailable"
        assert data["metrics_provenance"]["win_rate"]["reason"] in ("invalid_or_changed_source", "independent_approval_required")
    finally:
        database.DB_PATH = original_db
        if rel_db.exists():
            rel_db.unlink()


def test_self_approval_fails_closed(test_app, clean_db, tmp_path, monkeypatch):
    registry = tmp_path / "self_approval.json"
    monkeypatch.setenv("METRIC_APPROVALS_PATH", str(registry))

    rel_db = database.PROJECT_ROOT / "data" / "test_self.db"
    rel_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(clean_db, rel_db)

    original_db = database.DB_PATH
    database.DB_PATH = str(rel_db)

    try:
        fixed_time = datetime.datetime(2026, 9, 14, 10, 0, 0, tzinfo=datetime.timezone.utc)
        source_ref = str(rel_db.resolve().relative_to(database.PROJECT_ROOT.resolve())).replace("\\", "/")
        source_sha256 = hashlib.sha256(rel_db.read_bytes()).hexdigest()

        record = MetricRecord(
            metric_name="win_rate",
            value=0.5,
            unit="fraction",
            source_ref=source_ref,
            source_sha256=source_sha256,
            observed_at=fixed_time,
            collected_at=fixed_time,
            computed_at=fixed_time,
            owner="backend.app.data.database.get_risk_metrics",
            method_version="1.0",
            verification_status="unverified",
        )

        approval = {
            "metric_name": "win_rate",
            "metric_sha256": metric_digest(record),
            "reviewed_by": "backend.app.data.database.get_risk_metrics",
            "reviewed_at": (fixed_time + datetime.timedelta(hours=1)).isoformat(),
            "status": "approved",
        }
        registry.write_text(json.dumps({"version": 1, "approvals": [approval]}), encoding="utf-8")

        client = TestClient(test_app)
        response = client.get("/api/elite/risk_metrics")

        assert response.status_code == 200
        data = response.json()
        assert data["win_rate"] is None
        assert data["metrics_provenance"]["win_rate"]["verification_status"] == "unavailable"
        assert data["metrics_provenance"]["win_rate"]["reason"] == "independent_approval_required"
    finally:
        database.DB_PATH = original_db
        if rel_db.exists():
            rel_db.unlink()


def test_portfolio_valuation_unapproved_fails_closed(test_app, clean_db, empty_registry):
    client = TestClient(test_app)
    response = client.get("/api/portfolio")
    assert response.status_code == 200
    data = response.json()
    assert data["verification_status"] == "unavailable"
    assert data["value"] is None
    assert data["metrics_provenance"]["patrimonio_total"]["verification_status"] == "unavailable"


def test_unapproved_financial_fields_never_leak(test_app, clean_db, empty_registry):
    client = TestClient(test_app)
    keys = ("patrimonio_total", "patrimonio_reservado", "saldo_disponivel",
            "em_posicoes", "saldo_livre", "margem_operavel", "saldo_operavel")
    portfolio = client.get("/api/portfolio").json()
    positions = client.get("/api/positions").json()
    for response in (portfolio, positions["capital"]):
        for key in keys:
            assert response.get(key) is None, key
    for trade in positions["active_positions"] + positions["closed_positions"]:
        for key in ("entry_price", "exit_price", "target_price", "stop_loss",
                    "current_price", "alocado", "pnl_monetario", "pnl_pct"):
            assert trade.get(key) is None, key
    provenance = portfolio["metrics_provenance"]["patrimonio_total"]
    assert provenance.get("observed_at") is None
    assert provenance.get("collected_at") is None


def test_positions_unapproved_fails_closed(test_app, clean_db, empty_registry):
    client = TestClient(test_app)
    response = client.get("/api/positions")
    assert response.status_code == 200
    data = response.json()
    assert data["verification_status"] == "unavailable"
    assert data["value"] is None
    assert data["capital"]["verification_status"] == "unavailable"
    assert data["capital"]["value"] is None
    assert data["capital"]["metrics_provenance"]["patrimonio_total"]["verification_status"] == "unavailable"


def test_elimination_of_entry_price_fallback_in_compute_current_equity(clean_db):
    conn = sqlite3.connect(clean_db)
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, status) "
        "VALUES ('PETR4.SA', 'BUY', 100.0, 30.0, 'active')"
    )
    conn.commit()
    conn.close()

    with patch("backend.app.data.feed.get_current_price", return_value=0.0):
        assert database.compute_current_equity() is None

    with patch("backend.app.data.feed.get_current_price", return_value=-5.0):
        assert database.compute_current_equity() is None

    with patch("backend.app.data.feed.get_current_price", return_value=None):
        assert database.compute_current_equity() is None


def test_portfolio_and_positions_unavailable_when_feed_down(test_app, clean_db, empty_registry):
    conn = sqlite3.connect(clean_db)
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, status) "
        "VALUES ('PETR4.SA', 'BUY', 100.0, 30.0, 'active')"
    )
    conn.commit()
    conn.close()

    client = TestClient(test_app)
    with patch("backend.app.data.feed.get_current_price", return_value=0.0):
        resp_pf = client.get("/api/portfolio").json()
        assert resp_pf["patrimonio_total"] is None
        assert resp_pf["value"] is None
        assert resp_pf["verification_status"] == "unavailable"
        assert resp_pf["reason"] == "feed_price_unavailable"

        resp_pos = client.get("/api/positions").json()
        assert resp_pos["capital"]["patrimonio_total"] is None
        assert resp_pos["capital"]["value"] is None
        assert resp_pos["capital"]["verification_status"] == "unavailable"


def test_emergency_stop_does_not_use_entry_price_fallback(clean_db, monkeypatch):
    monkeypatch.setattr(main, "EMERGENCY_PASSWORD", "test-pass-123")
    conn = sqlite3.connect(clean_db)
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, status) "
        "VALUES ('PETR4.SA', 'BUY', 100.0, 30.0, 'active')"
    )
    conn.commit()
    conn.close()

    req = main.ActionRequest(action="stop", password="test-pass-123")
    with patch("backend.app.data.feed.get_current_price", return_value=0.0):
        with patch.object(main.ExecutorAgent, "close_order") as mock_close:
            resp = main.system_emergency_stop(req)
            mock_close.assert_not_called()
            assert resp["status"] == "success"


def test_no_synthetic_hardcoded_balance_emitted(test_app, clean_db, empty_registry):
    client = TestClient(test_app)
    for endpoint in ("/api/portfolio", "/api/positions", "/api/elite/risk_metrics"):
        response = client.get(endpoint)
        text = response.text
        assert "1000000" not in text
        assert "1.000.000" not in text
        assert "12480" not in text


def test_candle_integrity_rejection_preserved(test_app):
    client = TestClient(test_app)
    with patch("backend.app.data.feed.fetch_recent_data", return_value=None):
        resp = client.get("/api/candles/TESTE3")
        assert resp.status_code == 503

    corrupt_df = pd.DataFrame([
        {"date": "2026-09-10", "open": 0.0, "high": 12.0, "low": 9.0, "close": 11.0, "volume": 100.0}
    ])
    with patch("backend.app.data.feed.fetch_recent_data", return_value=corrupt_df):
        resp = client.get("/api/candles/TESTE3")
        assert resp.status_code == 502


def test_elimination_of_fallback_100_in_database_and_schema(tmp_path):
    """Verifica que o banco nunca mais insere ou retorna fallback sintético de 100.0."""
    db_file = tmp_path / "zero_capital.db"
    orig_db = database.DB_PATH
    database.DB_PATH = str(db_file)
    try:
        database.init_db()
        pf = database.get_portfolio()
        assert pf["saldo_disponivel"] == 0.0
        assert pf["saldo_livre"] == 0.0
        assert pf["saldo_operavel"] == 0.0
        assert pf["patrimonio_total"] == 0.0
    finally:
        database.DB_PATH = orig_db


def test_circuit_breaker_fail_closed_on_none_equity_without_error(clean_db):
    """Verifica que retorno null de equity aciona Circuit Breaker imediatamente sem crash."""
    from trading_bot.risk.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker()
    status = cb.check(current_equity=None, initial_equity=100.0, equity_start_of_day=100.0, equity_30d_ago=100.0)
    assert status.triggered is True
    assert "indisponível" in status.reason.lower()

    with patch("backend.app.data.feed.get_current_price", return_value=None):
        with patch.object(database, "DB_PATH", clean_db):
            can_trade = cb.can_trade()
            assert can_trade is False
