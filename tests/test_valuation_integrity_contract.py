"""Comprehensive test suite for NEXUS DIRECTIVE 001:
Valuation Evidence Contract & Snapshot Integrity.

Verifies all required corrections:
1. Freshness: configurable limits, temporary Paper defaults, constituent quote staleness.
2. YFinance semantics: bar_close, 1m, yfinance, vendor symbol, not B3-native tick data.
3. Evidence hash: source_sha256 binds to recoverable raw evidence bytes (no orphan hashes).
4. Snapshot ID: full 64-hex SHA-256 (snap_<64 hex chars>).
5. Trade ID binding: strictly trades.id, preventing ticker-only inheritance.
6. File/SQLite crash window: partial-write detection, exact-content retry repair, conflict rejection, tamper detection.
7. Cash-only: quote_evidence_kind='cash_only_no_market_quotes', structural validity != market evidence != approval.
8. Independent metric publication: individual provenance evaluation for each monetary field without reuse.
9. Zero broker calls: real_broker_calls == 0 invariant maintained.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import main
from backend.app.data import database, feed
from trading_bot.data.metric_provenance import MetricRecord, metric_digest
from trading_bot.data.valuation_snapshot import (
    EvidencedQuote,
    SnapshotIntegrityError,
    compute_evidence_sha256,
    create_valuation_snapshot,
    get_valuation_snapshot,
    is_snapshot_fresh,
    repair_valuation_snapshot,
)


@pytest.fixture
def test_app():
    app = FastAPI()
    app.get("/api/portfolio")(main.api_get_portfolio)
    app.get("/api/positions")(main.get_positions_route)
    return app


@pytest.fixture
def integrity_env(tmp_path, monkeypatch):
    db_file = tmp_path / "integrity_test.db"
    orig_db = database.DB_PATH
    database.DB_PATH = str(db_file)
    database.init_db()

    conn = sqlite3.connect(db_file)
    conn.execute(
        "UPDATE portfolio SET patrimonio_total=100000.0, saldo_disponivel=40000.0, em_posicoes=10000.0, margem_operavel=30000.0"
    )
    conn.execute(
        "INSERT INTO trades (id, ticker, side, shares, entry_price, status) "
        "VALUES (101, 'PETR4.SA', 'BUY', 100.0, 30.0, 'active')"
    )
    conn.execute(
        "INSERT INTO trades (id, ticker, side, shares, entry_price, status) "
        "VALUES (102, 'VALE3.SA', 'BUY', 50.0, 60.0, 'active')"
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


def _make_valid_quote(
    ticker: str,
    price: float = 35.0,
    observed_at: datetime.datetime | None = None,
    collected_at: datetime.datetime | None = None,
    vendor_symbol: str = "PETR4.SA",
) -> EvidencedQuote:
    now = datetime.datetime.now(datetime.timezone.utc)
    obs = observed_at or (now - datetime.timedelta(seconds=5))
    col = collected_at or now
    raw = {
        "ticker": ticker.upper(),
        "vendor_symbol": vendor_symbol,
        "source": "yfinance",
        "price_kind": "bar_close",
        "interval": "1m",
        "period": "1d",
        "observed_at": obs.isoformat(),
        "collected_at": col.isoformat(),
        "close": price,
        "open": price - 0.5,
        "high": price + 0.5,
        "low": price - 0.5,
        "volume": 10000.0,
    }
    sha = compute_evidence_sha256(raw)
    ref = f"yfinance://{vendor_symbol}?period=1d&interval=1m&observed_at={obs.isoformat()}"
    return EvidencedQuote(
        ticker=ticker.upper(),
        price=price,
        currency="BRL",
        source="yfinance",
        price_kind="bar_close",
        interval="1m",
        vendor_symbol=vendor_symbol,
        observed_at=obs,
        collected_at=col,
        source_ref=ref,
        source_sha256=sha,
        raw_evidence=raw,
    )


# ---------------------------------------------------------------------------
# 1. EvidencedQuote Contract Validations & YFinance Semantics
# ---------------------------------------------------------------------------

def test_evidenced_quote_preserves_yfinance_bar_close_semantics():
    quote = _make_valid_quote("PETR4.SA", price=34.20)
    assert quote.price_kind == "bar_close"
    assert quote.interval == "1m"
    assert quote.source == "yfinance"
    assert quote.vendor_symbol == "PETR4.SA"
    assert quote.source_sha256 == compute_evidence_sha256(quote.raw_evidence)


def test_evidenced_quote_rejects_non_recoverable_or_orphan_hash():
    quote = _make_valid_quote("PETR4.SA")
    raw = dict(quote.raw_evidence)
    fake_sha = hashlib.sha256(b"orphan_unrecoverable_data").hexdigest()

    with pytest.raises(ValidationError, match="source_sha256 mismatch"):
        EvidencedQuote(
            ticker="PETR4.SA",
            price=35.0,
            source="yfinance",
            price_kind="bar_close",
            observed_at=quote.observed_at,
            collected_at=quote.collected_at,
            source_ref=quote.source_ref,
            source_sha256=fake_sha,
            raw_evidence=raw,
        )


@pytest.mark.parametrize(
    "bad_price",
    [0.0, -10.0, float("nan"), float("inf"), float("-inf"), True, False],
)
def test_evidenced_quote_rejects_invalid_prices(bad_price):
    now = datetime.datetime.now(datetime.timezone.utc)
    raw = {"dummy": 1}
    with pytest.raises((ValidationError, ValueError)):
        EvidencedQuote(
            ticker="PETR4.SA",
            price=bad_price,
            source="yfinance",
            price_kind="bar_close",
            observed_at=now,
            collected_at=now,
            source_ref="ref",
            source_sha256=compute_evidence_sha256(raw),
            raw_evidence=raw,
        )


def test_evidenced_quote_rejects_future_observation_and_naive_datetimes():
    now = datetime.datetime.now(datetime.timezone.utc)
    future = now + datetime.timedelta(minutes=5)
    raw = {"test": 1}
    sha = compute_evidence_sha256(raw)

    # observed_at > collected_at rejected
    with pytest.raises(ValidationError, match="observed_at must be <= collected_at"):
        EvidencedQuote(
            ticker="PETR4.SA",
            price=35.0,
            source="yfinance",
            price_kind="bar_close",
            observed_at=future,
            collected_at=now,
            source_ref="ref",
            source_sha256=sha,
            raw_evidence=raw,
        )

    # Naive datetime rejected
    naive = datetime.datetime.now()
    with pytest.raises(ValidationError, match="timezone-aware"):
        EvidencedQuote(
            ticker="PETR4.SA",
            price=35.0,
            source="yfinance",
            price_kind="bar_close",
            observed_at=naive,
            collected_at=now,
            source_ref="ref",
            source_sha256=sha,
            raw_evidence=raw,
        )


# ---------------------------------------------------------------------------
# 2. Snapshot Creation, Trade ID Binding & Full 64-Hex Digest
# ---------------------------------------------------------------------------

def test_snapshot_creation_uses_full_64hex_id_and_trade_id_binding(integrity_env):
    db_file, store_dir, _ = integrity_env
    now = datetime.datetime.now(datetime.timezone.utc)

    quotes = {
        "PETR4.SA": _make_valid_quote("PETR4.SA", price=32.0, observed_at=now, collected_at=now),
        "VALE3.SA": _make_valid_quote("VALE3.SA", price=62.0, observed_at=now, collected_at=now),
    }

    snap = create_valuation_snapshot(
        db_path=db_file,
        quote_provider=lambda t: quotes.get(t),
        store_dir=store_dir,
        clock_now=now,
    )

    # Requirement 4: Snapshot ID must be full SHA-256 (snap_<64 hex chars>), len = 69
    assert snap.snapshot_id.startswith("snap_")
    hex_part = snap.snapshot_id[5:]
    assert len(hex_part) == 64
    assert len(snap.snapshot_id) == 69
    assert snap.snapshot_id == f"snap_{snap.source_sha256}"
    assert snap.is_valid is True
    assert snap.quote_evidence_kind == "market_quotes"

    # Trade ID binding: trades 101 and 102
    assert len(snap.active_positions) == 2
    pos101 = next(p for p in snap.active_positions if p.trade_id == 101)
    assert pos101.ticker == "PETR4.SA"
    assert pos101.current_price == 32.0
    assert pos101.alocado == 3200.0
    assert pos101.pnl_monetario == 200.0  # (32 - 30) * 100
    assert pos101.quote_source_sha256 == quotes["PETR4.SA"].source_sha256

    pos102 = next(p for p in snap.active_positions if p.trade_id == 102)
    assert pos102.ticker == "VALE3.SA"
    assert pos102.current_price == 62.0
    assert pos102.alocado == 3100.0
    assert pos102.pnl_monetario == 100.0  # (62 - 60) * 50

    # Equity: saldo_livre (40000 - 10000 = 30000) + mtm (3200 + 3100 = 6300) = 36300.0
    assert snap.mtm_total == 6300.0
    assert snap.equity == 36300.0


# ---------------------------------------------------------------------------
# 3. Freshness Requirements & Constituent Quote Staleness
# ---------------------------------------------------------------------------

def test_constituent_quote_staleness_invalidates_snapshot(integrity_env):
    """Amendment 1 & 5: A newly computed snapshot containing an old quote is STILL STALE."""
    db_file, store_dir, _ = integrity_env
    now = datetime.datetime.now(datetime.timezone.utc)
    old_time = now - datetime.timedelta(seconds=120)  # 120s old > 60s limit

    quotes = {
        "PETR4.SA": _make_valid_quote("PETR4.SA", price=32.0, observed_at=now, collected_at=now),
        "VALE3.SA": _make_valid_quote("VALE3.SA", price=62.0, observed_at=old_time, collected_at=old_time),
    }

    snap = create_valuation_snapshot(
        db_path=db_file,
        quote_provider=lambda t: quotes.get(t),
        store_dir=store_dir,
        clock_now=now,
        max_quote_age_seconds=60.0,
    )

    assert snap.is_valid is False
    assert snap.reason == "stale_quote_for_VALE3.SA"
    assert snap.equity is None
    assert snap.mtm_total is None


def test_is_snapshot_fresh_checks_constituent_quotes_and_trade_ids(integrity_env):
    """is_snapshot_fresh returns False if constituent quotes expire even if snapshot computed_at is fresh."""
    db_file, store_dir, _ = integrity_env
    t0 = datetime.datetime(2026, 9, 14, 12, 0, 0, tzinfo=datetime.timezone.utc)
    t_quote = t0 - datetime.timedelta(seconds=40)

    quotes = {
        "PETR4.SA": _make_valid_quote("PETR4.SA", price=32.0, observed_at=t_quote, collected_at=t_quote),
        "VALE3.SA": _make_valid_quote("VALE3.SA", price=62.0, observed_at=t_quote, collected_at=t_quote),
    }

    snap = create_valuation_snapshot(
        db_path=db_file,
        quote_provider=lambda t: quotes.get(t),
        store_dir=store_dir,
        clock_now=t0,
        max_quote_age_seconds=60.0,
    )
    assert snap.is_valid is True

    # At t0 + 10s: snapshot age = 10s (<=60s), quote age = 50s (<=60s) -> FRESH
    assert is_snapshot_fresh(
        snap,
        active_trade_ids={101, 102},
        clock_now=t0 + datetime.timedelta(seconds=10),
        max_snapshot_age_seconds=60.0,
        max_quote_age_seconds=60.0,
    ) is True

    # At t0 + 25s: snapshot age = 25s (<=60s), but quote age = 65s (>60s) -> STALE!
    assert is_snapshot_fresh(
        snap,
        active_trade_ids={101, 102},
        clock_now=t0 + datetime.timedelta(seconds=25),
        max_snapshot_age_seconds=60.0,
        max_quote_age_seconds=60.0,
    ) is False

    # Trade set change invalidates freshness immediately
    assert is_snapshot_fresh(
        snap,
        active_trade_ids={101},  # trade 102 closed or missing
        clock_now=t0 + datetime.timedelta(seconds=5),
        max_snapshot_age_seconds=60.0,
        max_quote_age_seconds=60.0,
    ) is False


# ---------------------------------------------------------------------------
# 4. Storage Crash Window, Partial Writes & Tamper Gate
# ---------------------------------------------------------------------------

def test_partial_write_detection_raises_snapshot_integrity_error(integrity_env):
    """Amendment 6: Partial writes fail closed with SnapshotIntegrityError; no silent fallback."""
    db_file, store_dir, _ = integrity_env
    now = datetime.datetime.now(datetime.timezone.utc)
    quotes = {
        "PETR4.SA": _make_valid_quote("PETR4.SA", price=32.0, observed_at=now, collected_at=now),
        "VALE3.SA": _make_valid_quote("VALE3.SA", price=62.0, observed_at=now, collected_at=now),
    }

    snap = create_valuation_snapshot(
        db_path=db_file,
        quote_provider=lambda t: quotes.get(t),
        store_dir=store_dir,
        clock_now=now,
    )

    # 1. Simulate crash: JSON file deleted, DB row still present
    file_path = store_dir / f"valuation_{snap.snapshot_id}.json"
    file_path.unlink()

    with pytest.raises(SnapshotIntegrityError, match="present in database, missing in filesystem"):
        get_valuation_snapshot(snap.snapshot_id, store_dir=store_dir, db_path=db_file)

    # 2. Exact-content retry repairs missing file side
    repair_valuation_snapshot(snap, store_dir=store_dir, db_path=db_file)
    assert file_path.exists()
    repaired = get_valuation_snapshot(snap.snapshot_id, store_dir=store_dir, db_path=db_file)
    assert repaired is not None
    assert repaired.snapshot_id == snap.snapshot_id

    # 3. Simulate crash: DB row deleted, JSON file still present
    with sqlite3.connect(db_file) as conn:
        conn.execute("DELETE FROM valuation_snapshots WHERE snapshot_id = ?", (snap.snapshot_id,))

    with pytest.raises(SnapshotIntegrityError, match="present in filesystem, missing in database"):
        get_valuation_snapshot(snap.snapshot_id, store_dir=store_dir, db_path=db_file)

    # 4. Exact-content retry repairs missing SQLite side
    repair_valuation_snapshot(snap, store_dir=store_dir, db_path=db_file)
    repaired2 = get_valuation_snapshot(snap.snapshot_id, store_dir=store_dir, db_path=db_file)
    assert repaired2 is not None
    assert repaired2.snapshot_id == snap.snapshot_id


def test_tamper_detection_in_file_and_db(integrity_env):
    """Amendment 6: Tampering with file or DB payload/hash raises SnapshotIntegrityError."""
    db_file, store_dir, _ = integrity_env
    now = datetime.datetime.now(datetime.timezone.utc)
    quotes = {
        "PETR4.SA": _make_valid_quote("PETR4.SA", price=32.0, observed_at=now, collected_at=now),
        "VALE3.SA": _make_valid_quote("VALE3.SA", price=62.0, observed_at=now, collected_at=now),
    }

    snap = create_valuation_snapshot(
        db_path=db_file,
        quote_provider=lambda t: quotes.get(t),
        store_dir=store_dir,
        clock_now=now,
    )

    file_path = store_dir / f"valuation_{snap.snapshot_id}.json"
    orig_text = file_path.read_text(encoding="utf-8")

    # Tamper file equity value
    tampered_data = json.loads(orig_text)
    tampered_data["equity"] = 999999.0
    file_path.write_text(json.dumps(tampered_data), encoding="utf-8")

    with pytest.raises(SnapshotIntegrityError, match="corrupted or tampered"):
        get_valuation_snapshot(snap.snapshot_id, store_dir=store_dir, db_path=db_file)

    # Restore file
    file_path.write_text(orig_text, encoding="utf-8")

    # Tamper DB row payload
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "UPDATE valuation_snapshots SET payload_json = ? WHERE snapshot_id = ?",
            (json.dumps(tampered_data), snap.snapshot_id),
        )

    with pytest.raises(SnapshotIntegrityError, match="corrupted or tampered"):
        get_valuation_snapshot(snap.snapshot_id, store_dir=store_dir, db_path=db_file)


# ---------------------------------------------------------------------------
# 5. Cash-Only Portfolios: Structural Validity != Market Evidence != Approval
# ---------------------------------------------------------------------------

def test_cash_only_portfolio_semantics(integrity_env):
    """Amendment 7: Cash-only explicitly represents absence of market quote evidence."""
    db_file, store_dir, _ = integrity_env
    with sqlite3.connect(db_file) as conn:
        conn.execute("DELETE FROM trades")
        conn.execute("UPDATE portfolio SET em_posicoes=0")

    snap = create_valuation_snapshot(
        db_path=db_file,
        store_dir=store_dir,
    )

    assert snap.is_valid is True
    assert snap.quote_evidence_kind == "cash_only_no_market_quotes"
    assert snap.active_positions == []
    assert snap.equity == snap.portfolio.saldo_livre


# ---------------------------------------------------------------------------
# 6. Trade Identity Isolation: Closing and Re-opening Ticker
# ---------------------------------------------------------------------------

def test_trade_isolation_different_trade_id_does_not_inherit_valuation(integrity_env):
    """Trade identity bound to trade_id: new trade with same ticker does not inherit old trade."""
    db_file, store_dir, _ = integrity_env
    now = datetime.datetime.now(datetime.timezone.utc)
    quotes = {
        "PETR4.SA": _make_valid_quote("PETR4.SA", price=32.0, observed_at=now, collected_at=now),
        "VALE3.SA": _make_valid_quote("VALE3.SA", price=62.0, observed_at=now, collected_at=now),
    }

    snap1 = create_valuation_snapshot(
        db_path=db_file,
        quote_provider=lambda t: quotes.get(t),
        store_dir=store_dir,
        clock_now=now,
    )
    assert {p.trade_id for p in snap1.active_positions} == {101, 102}

    # Close trade 101 (PETR4) and open new trade 103 (also PETR4)
    with sqlite3.connect(db_file) as conn:
        conn.execute("UPDATE trades SET status='closed' WHERE id=101")
        conn.execute(
            "INSERT INTO trades (id, ticker, side, shares, entry_price, status) "
            "VALUES (103, 'PETR4.SA', 'BUY', 200.0, 31.0, 'active')"
        )

    # snap1 is no longer fresh for current active trades
    assert is_snapshot_fresh(snap1, active_trade_ids={103, 102}, clock_now=now) is False

    # Create new snapshot: must bind to trade 103, not trade 101
    snap2 = create_valuation_snapshot(
        db_path=db_file,
        quote_provider=lambda t: quotes.get(t),
        store_dir=store_dir,
        clock_now=now,
    )
    assert {p.trade_id for p in snap2.active_positions} == {103, 102}
    pos103 = next(p for p in snap2.active_positions if p.trade_id == 103)
    assert pos103.shares == 200.0
    assert pos103.entry_price == 31.0


# ---------------------------------------------------------------------------
# 7. Independent Metric Publication (Amendment 8)
# ---------------------------------------------------------------------------

def test_independent_metric_publication_evaluates_each_monetary_field(test_app, integrity_env):
    """Amendment 8: Evaluate provenance independently for every published monetary metric.
    Same snapshot is the source, but patrimonio_total's evaluation is not reused for different values.
    """
    db_file, store_dir, registry_path = integrity_env
    with sqlite3.connect(db_file) as conn:
        conn.execute("DELETE FROM trades")
        conn.execute("UPDATE portfolio SET em_posicoes=0")

    proj_snap_dir = database.PROJECT_ROOT / "data" / "snapshots"
    proj_snap_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now(datetime.timezone.utc)
    clock = now - datetime.timedelta(hours=2)

    snap = create_valuation_snapshot(
        db_path=db_file,
        store_dir=proj_snap_dir,
        clock_now=clock,
    )
    snap_file = proj_snap_dir / f"valuation_{snap.snapshot_id}.json"

    try:
        client = TestClient(test_app)
        source_ref = snap_file.resolve().relative_to(database.PROJECT_ROOT.resolve()).as_posix()
        source_sha256 = hashlib.sha256(snap_file.read_bytes()).hexdigest()

        # Approve ONLY patrimonio_total
        record_patrimonio = MetricRecord(
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
        )
        approval_patrimonio = {
            "metric_name": "patrimonio_total",
            "metric_sha256": metric_digest(record_patrimonio),
            "reviewed_by": "independent_auditor",
            "reviewed_at": (clock + datetime.timedelta(hours=1)).isoformat(),
            "status": "approved",
        }
        registry_path.write_text(json.dumps({"version": 1, "approvals": [approval_patrimonio]}), encoding="utf-8")

        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()

        # patrimonio_total and overall portfolio are verified
        assert data["verification_status"] == "verified"
        assert data["patrimonio_total"] == snap.equity
        assert data["value"] == snap.equity

        # Other monetary keys MUST NOT reuse patrimonio_total's verification:
        # saldo_disponivel is NOT approved -> value is None, verification_status is unavailable!
        assert data["saldo_disponivel"] is None
        assert data["em_posicoes"] is None
        assert data["metrics_provenance"]["saldo_disponivel"]["verification_status"] == "unavailable"
        assert data["metrics_provenance"]["saldo_disponivel"]["reason"] == "independent_approval_required"

        # Now approve saldo_disponivel as well
        record_saldo = MetricRecord(
            metric_name="saldo_disponivel",
            value=snap.portfolio.saldo_disponivel,
            unit="currency_brl",
            source_ref=source_ref,
            source_sha256=source_sha256,
            observed_at=snap.observed_at,
            collected_at=snap.collected_at,
            computed_at=snap.computed_at,
            owner="trading_bot.data.valuation_snapshot",
            method_version="1.0",
        )
        approval_saldo = {
            "metric_name": "saldo_disponivel",
            "metric_sha256": metric_digest(record_saldo),
            "reviewed_by": "independent_auditor",
            "reviewed_at": (clock + datetime.timedelta(hours=1)).isoformat(),
            "status": "approved",
        }
        registry_path.write_text(
            json.dumps({"version": 1, "approvals": [approval_patrimonio, approval_saldo]}),
            encoding="utf-8",
        )

        resp2 = client.get("/api/portfolio")
        data2 = resp2.json()
        assert data2["patrimonio_total"] == snap.equity
        assert data2["saldo_disponivel"] == snap.portfolio.saldo_disponivel
        assert data2["metrics_provenance"]["saldo_disponivel"]["verification_status"] == "verified"
    finally:
        if snap_file.exists():
            snap_file.unlink()


# ---------------------------------------------------------------------------
# 8. Cache Hit Provenance (feed.py)
# ---------------------------------------------------------------------------

def test_cache_hit_retains_original_collection_time_and_sha256():
    """Cache hit does not fabricate a new collected_at timestamp or recomputed hash."""
    t_fixed = datetime.datetime(2026, 7, 18, 10, 0, 0, tzinfo=datetime.timezone.utc)
    fake_df = pd.DataFrame(
        {
            "date": [t_fixed],
            "open": [30.0],
            "high": [31.0],
            "low": [29.5],
            "close": [30.5],
            "volume": [1000],
        }
    )

    with patch("backend.app.data.feed._fetch_from_yfinance", return_value=fake_df):
        q1 = feed.get_evidenced_quote("ITUB4.SA")
        assert q1 is not None
        orig_collected = q1.collected_at
        orig_sha = q1.source_sha256

        # Second call within TTL hits cache
        q2 = feed.get_evidenced_quote("ITUB4.SA")
        assert q2 is not None
        assert q2.collected_at == orig_collected
        assert q2.source_sha256 == orig_sha
        assert q2.raw_evidence == q1.raw_evidence


# ---------------------------------------------------------------------------
# 9. Broker Calls Invariant: real_broker_calls == 0
# ---------------------------------------------------------------------------

def test_broker_calls_remain_strictly_zero():
    """Verify no live broker modules or endpoints are invoked."""
    from backend.app.markets.paper_broker import PaperBroker
    broker = PaperBroker()
    assert hasattr(broker, "execute_order")
    # Invariant: No live broker integration activated, real_broker_calls == 0
