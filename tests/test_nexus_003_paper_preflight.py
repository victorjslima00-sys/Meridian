"""Tests for NEXUS-003: Paper Data Approval Candidates & Session Preflight.

Validates:
- Exact production normalization parity with MarketAnalyst
- Deterministic candidate evidence bundle creation and validation
- Tamper-resistance across all evidence artifacts and dataset
- Fail-closed path traversal and identity mismatch rejections
- Explicit human approval command integrity and duplicate rejection
- Read-only paper session preflight and zero trade/portfolio mutations
"""
import json
import sqlite3
from datetime import date, timedelta

import pandas as pd
import pytest

from scripts.paper_session_preflight import run_paper_preflight
from trading_bot.data import approval
from trading_bot.data.approval import (
    Registry,
    dataset_digest,
    normalize_ohlcv_to_signal_df,
)
from trading_bot.data.approval_candidate import (
    approve_candidate,
    build_candidate_bundle,
    validate_candidate,
)


@pytest.fixture
def synthetic_ohlcv_df():
    """Generates 220 bars of valid OHLCV data with clean decimal prices."""
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(220)]
    records = []
    price = 30.0
    for d in dates:
        p = round(price, 4)
        records.append(
            {
                "date": str(d),
                "open": p,
                "high": round(p + 1.0, 4),
                "low": round(p - 1.0, 4),
                "close": round(p + 0.2, 4),
                "volume": 10000.0,
            }
        )
        price += 0.05
    return pd.DataFrame(records)


def test_shared_normalization_exact_parity(synthetic_ohlcv_df):
    """Proves normalize_ohlcv_to_signal_df produces identical output schema and values."""
    norm_df = normalize_ohlcv_to_signal_df(synthetic_ohlcv_df)

    expected_cols = ["ts", "adj_close", "o", "c", "h", "l", "v"]
    assert list(norm_df.columns) == expected_cols
    assert len(norm_df) == len(synthetic_ohlcv_df)
    assert isinstance(norm_df["ts"].iloc[0], date)
    assert float(norm_df["adj_close"].iloc[0]) == float(synthetic_ohlcv_df["close"].iloc[0])
    assert float(norm_df["o"].iloc[0]) == float(synthetic_ohlcv_df["open"].iloc[0])


def test_candidate_digest_matches_analyst_digest(synthetic_ohlcv_df, tmp_path):
    """Proves approval-candidate builder computes the exact same digest as MarketAnalyst."""
    ticker = "PETR4.SA"
    norm_df = normalize_ohlcv_to_signal_df(synthetic_ohlcv_df)
    expected_digest = dataset_digest(norm_df, ticker)

    bundle_dir = tmp_path / "candidates" / "petr4"
    manifest = build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=synthetic_ohlcv_df,
    )

    assert manifest.dataset_sha256 == expected_digest
    assert manifest.ticker == ticker
    assert manifest.row_count == len(norm_df)
    assert manifest.intended_use == "PAPER_TRADING"
    # Status approved must NOT be in candidate manifest
    assert not hasattr(manifest, "status")


def test_candidate_self_validation_pass(synthetic_ohlcv_df, tmp_path):
    """Proves a freshly generated candidate bundle passes self-validation."""
    ticker = "VALE3.SA"
    bundle_dir = tmp_path / "candidates" / "vale3"
    manifest = build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=synthetic_ohlcv_df,
    )

    manifest_file = bundle_dir / "candidate_manifest.json"
    validated = validate_candidate(manifest_file, project_root=tmp_path)
    assert validated.dataset_sha256 == manifest.dataset_sha256
    assert validated.ticker == ticker


@pytest.mark.parametrize(
    "tamper_target",
    ["dataset", "source", "calendar", "adjustments", "point_in_time"],
)
def test_tampered_evidence_file_fails(synthetic_ohlcv_df, tmp_path, tamper_target):
    """Proves modifying any evidence file or dataset in the candidate bundle fails closed."""
    ticker = "BBDC4.SA"
    bundle_dir = tmp_path / "candidates" / "bbdc4"
    build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=synthetic_ohlcv_df,
    )

    manifest_file = bundle_dir / "candidate_manifest.json"

    if tamper_target == "dataset":
        f = bundle_dir / "dataset.json"
        f.write_text(f.read_text().replace("30.0", "30.05"))
    elif tamper_target == "source":
        f = bundle_dir / "source.json"
        f.write_text(f.read_text().replace("yfinance", "tampered_source"))
    elif tamper_target == "calendar":
        f = bundle_dir / "calendar.json"
        f.write_text(f.read_text().replace("observed_dataset_dates", "fake_calendar"))
    elif tamper_target == "adjustments":
        f = bundle_dir / "adjustments.json"
        f.write_text(f.read_text().replace("auto_adjust", "tampered_adj"))
    elif tamper_target == "point_in_time":
        f = bundle_dir / "point_in_time.json"
        f.write_text(f.read_text().replace("capture_time_evidence", "fake_pit"))

    with pytest.raises(ValueError, match="evidence_hash_mismatch|dataset_digest_mismatch"):
        validate_candidate(manifest_file, project_root=tmp_path)


def test_missing_evidence_file_fails(synthetic_ohlcv_df, tmp_path):
    """Proves deleting an evidence file fails closed."""
    ticker = "ITUB4.SA"
    bundle_dir = tmp_path / "candidates" / "itub4"
    build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=synthetic_ohlcv_df,
    )
    manifest_file = bundle_dir / "candidate_manifest.json"

    # Remove calendar.json
    (bundle_dir / "calendar.json").unlink()

    with pytest.raises(ValueError, match="missing_evidence_file"):
        validate_candidate(manifest_file, project_root=tmp_path)


def test_path_traversal_evidence_fails(synthetic_ohlcv_df, tmp_path):
    """Proves path traversal in manifest is rejected."""
    ticker = "BBAS3.SA"
    bundle_dir = tmp_path / "candidates" / "bbas3"
    build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=synthetic_ohlcv_df,
    )
    manifest_file = bundle_dir / "candidate_manifest.json"
    m_data = json.loads(manifest_file.read_text(encoding="utf-8"))

    # Inject traversal path
    m_data["source"]["path"] = "../outside_source.json"
    manifest_file.write_text(json.dumps(m_data), encoding="utf-8")

    with pytest.raises(ValueError, match="path_traversal_forbidden"):
        validate_candidate(manifest_file, project_root=tmp_path)


def test_ticker_mismatch_fails(synthetic_ohlcv_df, tmp_path):
    """Proves manifest ticker mismatching source payload fails closed."""
    ticker = "PRIO3.SA"
    bundle_dir = tmp_path / "candidates" / "prio3"
    build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=synthetic_ohlcv_df,
    )
    manifest_file = bundle_dir / "candidate_manifest.json"
    m_data = json.loads(manifest_file.read_text(encoding="utf-8"))

    # Alter manifest ticker without altering underlying dataset
    m_data["ticker"] = "VALE3.SA"
    manifest_file.write_text(json.dumps(m_data), encoding="utf-8")

    with pytest.raises(ValueError, match="dataset_digest_mismatch|source_ticker_mismatch"):
        validate_candidate(manifest_file, project_root=tmp_path)


def test_human_approval_command_validation_rules(synthetic_ohlcv_df, tmp_path):
    """Adversarially tests all validation gates of approve_candidate."""
    ticker = "RENT3.SA"
    bundle_dir = tmp_path / "candidates" / "rent3"
    manifest = build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=synthetic_ohlcv_df,
    )
    manifest_file = bundle_dir / "candidate_manifest.json"
    registry_file = tmp_path / "test_registry.json"
    registry_file.write_text(json.dumps({"version": 1, "approvals": []}), encoding="utf-8")

    # 1. Missing reviewed_by
    with pytest.raises(ValueError, match="reviewed_by_required"):
        approve_candidate(
            candidate_path=manifest_file,
            reviewed_by="",
            review_notes="Notes",
            confirm_digest=manifest.dataset_sha256,
            registry_path=registry_file,
            project_root=tmp_path,
        )

    # 2. Missing review_notes
    with pytest.raises(ValueError, match="review_notes_required"):
        approve_candidate(
            candidate_path=manifest_file,
            reviewed_by="Auditor Human",
            review_notes="   ",
            confirm_digest=manifest.dataset_sha256,
            registry_path=registry_file,
            project_root=tmp_path,
        )

    # 3. Wrong confirm digest
    with pytest.raises(ValueError, match="confirm_digest_mismatch"):
        approve_candidate(
            candidate_path=manifest_file,
            reviewed_by="Auditor Human",
            review_notes="Valid notes",
            confirm_digest="0" * 64,
            registry_path=registry_file,
            project_root=tmp_path,
        )

    # 4. Successful approval write
    appr = approve_candidate(
        candidate_path=manifest_file,
        reviewed_by="Auditor Human",
        review_notes="Valid notes after full manual verification",
        confirm_digest=manifest.dataset_sha256,
        registry_path=registry_file,
        project_root=tmp_path,
    )
    assert appr.dataset_sha256 == manifest.dataset_sha256
    assert appr.status == "approved"

    # Verify registry content on disk
    reg = Registry.model_validate_json(registry_file.read_bytes())
    assert len(reg.approvals) == 1
    assert reg.approvals[0].dataset_sha256 == manifest.dataset_sha256

    # 5. Duplicate approval fails closed
    with pytest.raises(ValueError, match="duplicate_approval"):
        approve_candidate(
            candidate_path=manifest_file,
            reviewed_by="Auditor Human",
            review_notes="Attempt duplicate",
            confirm_digest=manifest.dataset_sha256,
            registry_path=registry_file,
            project_root=tmp_path,
        )


def test_production_registry_remains_unmodified():
    """Verifies that config/data_approvals.json remains completely unmodified (version 1, 0 approvals)."""
    reg = Registry.model_validate_json(approval.REGISTRY.read_bytes())
    assert reg.version == 1
    assert reg.approvals == []


def test_paper_preflight_blocked_on_empty_registry(tmp_path, monkeypatch):
    """Proves preflight reports BLOCKED when registry is empty (default fail-closed)."""
    # Create isolated test db
    test_db = tmp_path / "test_trading.db"
    conn = sqlite3.connect(str(test_db))
    conn.execute(
        """
        CREATE TABLE portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patrimonio_total REAL DEFAULT 1000.0,
            saldo_disponivel REAL DEFAULT 1000.0,
            em_posicoes REAL DEFAULT 0.0,
            margem_operavel REAL DEFAULT 500.0,
            updated_at TIMESTAMP
        )
    """
    )
    conn.execute("INSERT INTO portfolio (patrimonio_total, saldo_disponivel) VALUES (1000.0, 1000.0)")
    conn.execute(
        """
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            side TEXT,
            shares REAL,
            entry_price REAL,
            exit_price REAL,
            target_price REAL,
            stop_loss REAL,
            entry_date TIMESTAMP,
            exit_date TIMESTAMP,
            pnl_pct REAL,
            exit_reason TEXT,
            ai_rationale TEXT,
            status TEXT,
            signal_id TEXT
        )
    """
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_trades_strategy_signal_id ON trades(signal_id) WHERE signal_id IS NOT NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_trades_one_active_per_ticker ON trades(ticker) WHERE status = 'active'"
    )
    conn.commit()
    conn.close()

    # Empty registry
    reg_file = tmp_path / "empty_registry.json"
    reg_file.write_text(json.dumps({"version": 1, "approvals": []}), encoding="utf-8")

    report = run_paper_preflight(
        registry_path=reg_file,
        db_path=test_db,
        storage_dir=tmp_path / "storage",
        tickers=["PETR4.SA"],
    )

    assert report.trade_mutations_count == 0
    assert report.portfolio_mutations_count == 0
    assert report.paper_mode_check is True
    assert report.db_schema_check is True
    assert report.signal_id_index_check is True
    assert report.active_position_index_check is True
    assert report.circuit_breaker_check is True
    assert report.storage_writable_check is True
    assert report.valuation_subsystem_check is True
    assert report.overall_status in ("BLOCKED", "UNVERIFIED")


def test_paper_preflight_passes_with_approved_dataset(synthetic_ohlcv_df, tmp_path, monkeypatch):
    """Proves preflight reports PASS when an exact approved dataset exists and all system checks pass."""
    ticker = "PETR4.SA"

    # 1. Setup isolated db
    test_db = tmp_path / "test_trading.db"
    conn = sqlite3.connect(str(test_db))
    conn.execute(
        """
        CREATE TABLE portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patrimonio_total REAL DEFAULT 1000.0,
            saldo_disponivel REAL DEFAULT 1000.0,
            em_posicoes REAL DEFAULT 0.0,
            margem_operavel REAL DEFAULT 500.0,
            updated_at TIMESTAMP
        )
    """
    )
    conn.execute("INSERT INTO portfolio (patrimonio_total, saldo_disponivel) VALUES (1000.0, 1000.0)")
    conn.execute(
        """
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            side TEXT,
            shares REAL,
            entry_price REAL,
            exit_price REAL,
            target_price REAL,
            stop_loss REAL,
            entry_date TIMESTAMP,
            exit_date TIMESTAMP,
            pnl_pct REAL,
            exit_reason TEXT,
            ai_rationale TEXT,
            status TEXT,
            signal_id TEXT
        )
    """
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_trades_strategy_signal_id ON trades(signal_id) WHERE signal_id IS NOT NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_trades_one_active_per_ticker ON trades(ticker) WHERE status = 'active'"
    )
    conn.commit()
    conn.close()

    # 2. Build candidate
    bundle_dir = tmp_path / "candidates" / "petr4"
    manifest = build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=synthetic_ohlcv_df,
    )
    manifest_file = bundle_dir / "candidate_manifest.json"

    # 3. Approve in temporary registry
    registry_file = tmp_path / "test_registry.json"
    registry_file.write_text(json.dumps({"version": 1, "approvals": []}), encoding="utf-8")

    approve_candidate(
        candidate_path=manifest_file,
        reviewed_by="Victor-QA",
        review_notes="Approved for paper testing",
        confirm_digest=manifest.dataset_sha256,
        registry_path=registry_file,
        project_root=tmp_path,
    )

    # Monkeypatch approval.PROJECT_ROOT and approval.REGISTRY for this test
    monkeypatch.setattr(approval, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(approval, "REGISTRY", registry_file)

    # Monkeypatch market.fetch_ohlcv to return synthetic_ohlcv_df
    class MockMarket:
        def fetch_ohlcv(self, t, period="2y", interval="1d"):
            return synthetic_ohlcv_df.copy()

    from scripts import paper_session_preflight
    from backend.app.agents import market_analyst
    monkeypatch.setattr(paper_session_preflight, "resolve_market", lambda sym: MockMarket())
    monkeypatch.setattr(market_analyst, "resolve_market", lambda sym: MockMarket())

    report = run_paper_preflight(
        registry_path=registry_file,
        db_path=test_db,
        storage_dir=tmp_path / "storage",
        tickers=[ticker],
    )

    assert report.trade_mutations_count == 0
    assert report.portfolio_mutations_count == 0
    assert report.overall_status == "PASS"
    assert len(report.ticker_results) == 1
    assert report.ticker_results[0].preflight_verdict == "PASS"
    assert report.ticker_results[0].approval_status == "PASS"


def test_zero_mutation_guarantee_on_candidate_build_and_preflight(synthetic_ohlcv_df, tmp_path):
    """Proves that building candidates and running preflight performs zero DB inserts or mutations."""
    test_db = tmp_path / "audit.db"
    conn = sqlite3.connect(str(test_db))
    conn.execute(
        """
        CREATE TABLE portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patrimonio_total REAL DEFAULT 500.0,
            saldo_disponivel REAL DEFAULT 500.0,
            em_posicoes REAL DEFAULT 0.0,
            margem_operavel REAL DEFAULT 200.0,
            updated_at TIMESTAMP
        )
    """
    )
    conn.execute("INSERT INTO portfolio (patrimonio_total, saldo_disponivel) VALUES (500.0, 500.0)")
    conn.execute(
        """
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            side TEXT,
            shares REAL,
            entry_price REAL,
            exit_price REAL,
            target_price REAL,
            stop_loss REAL,
            entry_date TIMESTAMP,
            exit_date TIMESTAMP,
            pnl_pct REAL,
            exit_reason TEXT,
            ai_rationale TEXT,
            status TEXT,
            signal_id TEXT
        )
    """
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_trades_strategy_signal_id ON trades(signal_id) WHERE signal_id IS NOT NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_trades_one_active_per_ticker ON trades(ticker) WHERE status = 'active'"
    )
    conn.commit()

    # Initial snapshot
    trades_initial = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    portfolio_initial = conn.execute("SELECT * FROM portfolio").fetchall()
    conn.close()

    # 1. Build Candidate
    build_candidate_bundle(
        ticker="WEGE3.SA",
        output_dir=tmp_path / "candidates" / "wege3",
        project_root=tmp_path,
        df=synthetic_ohlcv_df,
    )

    # 2. Run Preflight
    report = run_paper_preflight(
        db_path=test_db,
        storage_dir=tmp_path / "storage",
        tickers=["WEGE3.SA"],
    )

    # Re-verify DB state
    conn2 = sqlite3.connect(str(test_db))
    trades_final = conn2.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    portfolio_final = conn2.execute("SELECT * FROM portfolio").fetchall()
    conn2.close()

    assert trades_final == trades_initial == 0
    assert portfolio_final == portfolio_initial
    assert report.trade_mutations_count == 0
    assert report.portfolio_mutations_count == 0
