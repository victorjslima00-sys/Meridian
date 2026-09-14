"""Tests for SnapshotValuation (Ticket P0 - Dados + Integração).

Verifies:
1. Exact preservation of active positions, balances, quotes, unit, and timestamps.
2. Fail-closed on missing feed quote without fallback to entry_price.
3. Stable deterministic snapshot_id and SHA-256 reproducibility across re-queries.
4. Independent approval lifecycle: unapproved -> approved in registry -> verified API publication.
"""
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.data import database
from trading_bot.data.metric_provenance import MetricRecord, metric_digest
from trading_bot.data.valuation_snapshot import (
    ValuationSnapshot,
    create_valuation_snapshot,
    get_latest_valuation_snapshot,
    get_valuation_snapshot,
)


@pytest.fixture
def test_app():
    app = FastAPI()
    app.get("/api/portfolio")(main.api_get_portfolio)
    app.get("/api/positions")(main.get_positions_route)
    return app


@pytest.fixture
def snapshot_env(tmp_path, monkeypatch):
    db_file = tmp_path / "valuation_test.db"
    orig_db = database.DB_PATH
    database.DB_PATH = str(db_file)
    database.init_db()

    conn = sqlite3.connect(db_file)
    conn.execute(
        "UPDATE portfolio SET patrimonio_total=50000.0, saldo_disponivel=10000.0, em_posicoes=3000.0, margem_operavel=20000.0"
    )
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, status) "
        "VALUES ('PETR4.SA', 'BUY', 100.0, 30.0, 'active')"
    )
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, status) "
        "VALUES ('VALE3.SA', 'BUY', 50.0, 60.0, 'active')"
    )
    conn.commit()
    conn.close()

    registry_path = tmp_path / "metric_approvals.json"
    registry_path.write_text(json.dumps({"version": 1, "approvals": []}), encoding="utf-8")
    monkeypatch.setenv("METRIC_APPROVALS_PATH", str(registry_path))

    store_dir = tmp_path / "snapshots"
    store_dir.mkdir(parents=True, exist_ok=True)

    yield db_file, store_dir, registry_path

    database.DB_PATH = orig_db


def test_snapshot_preserves_balances_but_rejects_untraceable_quotes(snapshot_env):
    db_file, store_dir, _ = snapshot_env
    quotes = {"PETR4.SA": 32.50, "VALE3.SA": 64.00}
    clock = datetime.datetime(2026, 9, 14, 11, 0, 0, tzinfo=datetime.timezone.utc)

    snap = create_valuation_snapshot(
        db_path=db_file,
        price_provider=lambda t: quotes.get(t),
        store_dir=store_dir,
        clock_now=clock,
    )

    assert snap.is_valid is False
    assert snap.reason == "quote_evidence_required_for_VALE3.SA"
    assert snap.unit == "currency_brl"
    assert snap.observed_at == clock
    assert snap.collected_at == clock
    assert snap.computed_at == clock

    # Check portfolio balances frozen
    assert snap.portfolio.saldo_disponivel == 10000.0
    assert snap.portfolio.em_posicoes == 3000.0
    assert snap.portfolio.saldo_livre == 7000.0
    assert snap.portfolio.margem_operavel == 20000.0
    assert snap.portfolio.patrimonio_total == 50000.0

    # Check positions frozen
    assert len(snap.active_positions) == 2
    pos_petr = [p for p in snap.active_positions if p.ticker == "PETR4.SA"][0]
    assert pos_petr.shares == 100.0
    assert pos_petr.entry_price == 30.0
    assert pos_petr.current_price is None
    assert pos_petr.alocado is None
    assert pos_petr.pnl_monetario is None
    assert pos_petr.pnl_pct is None
    assert pos_petr.quote_observed_at is None
    assert pos_petr.quote_source is None

    pos_vale = [p for p in snap.active_positions if p.ticker == "VALE3.SA"][0]
    assert pos_vale.shares == 50.0
    assert pos_vale.entry_price == 60.0
    assert pos_vale.current_price is None
    assert pos_vale.alocado is None
    assert pos_vale.pnl_monetario is None

    # Untraceable scalar quotes cannot establish market valuation.
    assert snap.mtm_total is None
    assert snap.equity is None
    assert snap.source_sha256 is not None
    assert len(snap.source_sha256) == 64


def test_missing_feed_quote_blocks_valuation_without_entry_price_fallback(snapshot_env):
    db_file, store_dir, _ = snapshot_env
    # VALE3 quote is missing (None)
    quotes = {"PETR4.SA": 32.50, "VALE3.SA": None}

    snap = create_valuation_snapshot(
        db_path=db_file,
        price_provider=lambda t: quotes.get(t),
        store_dir=store_dir,
    )

    assert snap.is_valid is False
    assert snap.equity is None
    assert snap.mtm_total is None
    assert snap.reason == "feed_price_unavailable_for_VALE3.SA"

    pos_vale = [p for p in snap.active_positions if p.ticker == "VALE3.SA"][0]
    assert pos_vale.current_price is None
    assert pos_vale.alocado is None
    assert pos_vale.pnl_monetario is None
    # Crucial: entry_price (60.0) was NOT used to fake current_price!
    assert pos_vale.entry_price == 60.0


def test_snapshot_requery_reproduces_identical_hash_and_values(snapshot_env):
    db_file, store_dir, _ = snapshot_env
    quotes = {"PETR4.SA": 32.50, "VALE3.SA": 64.00}

    snap1 = create_valuation_snapshot(
        db_path=db_file,
        price_provider=lambda t: quotes.get(t),
        store_dir=store_dir,
    )

    # Re-fetch by snapshot_id
    snap2 = get_valuation_snapshot(snap1.snapshot_id, store_dir=store_dir, db_path=db_file)
    assert snap2 is not None
    assert snap2.snapshot_id == snap1.snapshot_id
    assert snap2.source_sha256 == snap1.source_sha256
    assert snap2.equity == snap1.equity
    assert snap2.observed_at == snap1.observed_at

    # Re-fetch latest
    snap3 = get_latest_valuation_snapshot(store_dir=store_dir, db_path=db_file)
    assert snap3 is not None
    assert snap3.snapshot_id == snap1.snapshot_id
    assert snap3.source_sha256 == snap1.source_sha256


def test_independent_approval_lifecycle_for_valuation_snapshot(test_app, snapshot_env):
    db_file, store_dir, registry_path = snapshot_env
    # Explicitly synthetic cash-only example: scalar mocks are not quote evidence.
    with sqlite3.connect(db_file) as conn:
        conn.execute("DELETE FROM trades")
        conn.execute("UPDATE portfolio SET em_posicoes=0")
    quotes = {"PETR4.SA": 30.00, "VALE3.SA": 60.00}
    now = datetime.datetime.now(datetime.timezone.utc)
    clock = now - datetime.timedelta(hours=2)

    # Put db into project root structure for relative path verification in provenance
    proj_snap_dir = database.PROJECT_ROOT / "data" / "snapshots"
    proj_snap_dir.mkdir(parents=True, exist_ok=True)

    snap = create_valuation_snapshot(
        db_path=db_file,
        price_provider=lambda t: quotes.get(t),
        store_dir=proj_snap_dir,
        clock_now=clock,
    )

    snap_file = proj_snap_dir / f"valuation_{snap.snapshot_id}.json"

    try:
        client = TestClient(test_app)
        with patch("backend.app.data.feed.get_current_price", side_effect=lambda t: quotes.get(t)):
            # 1. Unapproved: fails closed, returns unavailable with null monetary fields
            resp = client.get("/api/portfolio")
            assert resp.status_code == 200
            data = resp.json()
            assert data["verification_status"] == "unavailable"
            assert data["patrimonio_total"] is None
            assert data["value"] is None

            # 2. Independent auditor reviews snapshot file and adds approval to registry
            source_ref = snap_file.resolve().relative_to(database.PROJECT_ROOT.resolve()).as_posix()
            source_sha256 = hashlib.sha256(snap_file.read_bytes()).hexdigest()

            record = MetricRecord(
                metric_name="patrimonio_total",
                value=snap.equity,
                unit="currency_brl",
                source_ref=source_ref,
                source_sha256=source_sha256,
                observed_at=snap.observed_at,
                collected_at=snap.collected_at,
                computed_at=snap.computed_at,
                owner="trading_bot.data.valuation_snapshot",
                method_version="1.0",
                verification_status="unverified",
            )

            approval = {
                "metric_name": "patrimonio_total",
                "metric_sha256": metric_digest(record),
                "reviewed_by": "independent_chief_auditor",
                "reviewed_at": (clock + datetime.timedelta(hours=1)).isoformat(),
                "status": "approved",
            }
            registry_path.write_text(json.dumps({"version": 1, "approvals": [approval]}), encoding="utf-8")

            # 3. Re-querying publishes verified valuation!
            resp_approved = client.get("/api/portfolio")
            assert resp_approved.status_code == 200
            data_appr = resp_approved.json()
            assert data_appr["verification_status"] == "verified"
            assert data_appr["value"] == snap.equity
            assert data_appr["patrimonio_total"] == snap.equity

            # 4. Positions route publishes the same cash-only snapshot
            pos_resp = client.get("/api/positions")
            assert pos_resp.status_code == 200
            pos_data = pos_resp.json()
            assert pos_data["verification_status"] == "verified"
            assert pos_data["active_positions"] == []

            # 5. Subsequent query reproduces exact verified state (idempotency)
            resp_repeat = client.get("/api/portfolio")
            assert resp_repeat.json() == data_appr
    finally:
        if snap_file.exists():
            snap_file.unlink()
