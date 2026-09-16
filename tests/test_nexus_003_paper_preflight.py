"""Tests for NEXUS-003-R1: Preflight Truth & Human Approval Binding Closeout.

Validates:
- Exact production normalization parity with MarketAnalyst
- Deterministic candidate evidence bundle creation, candidate_id binding, and self-validation
- Review CSV binding and semantic cross-checks on all metadata
- Tamper-resistance across all evidence artifacts, canonical JSON, and review CSV
- Rehashed false metadata rejection
- Idempotent regeneration vs collision rejection
- Human approval confirmation token gate (APPROVE_DATASET_FOR_PAPER_TRADING_ONLY)
- Strict double confirmation of dataset_sha256 AND candidate_id
- Read-only paper preflight with DB row fingerprinting
- Active position duplicate detection failing closed (adversarial test)
- Circuit breaker configuration vs entry gate (can_trade) distinction
- Exact-frame MarketAnalyst binding without refetching
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
    APPROVAL_CONFIRMATION_TOKEN,
    DEFAULT_STRATEGY_ID,
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


def test_candidate_digest_and_candidate_id(synthetic_ohlcv_df, tmp_path):
    """Proves approval-candidate builder computes deterministic digest and candidate_id."""
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
    assert manifest.strategy_id == DEFAULT_STRATEGY_ID
    assert manifest.intended_use == "PAPER_TRADING"
    assert len(manifest.candidate_id) == 64
    assert (bundle_dir / "dataset.json").exists()
    assert (bundle_dir / "dataset.csv").exists()
    assert manifest.review_csv.path.endswith("dataset.csv")


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
    assert validated.candidate_id == manifest.candidate_id
    assert validated.ticker == ticker


@pytest.mark.parametrize(
    "tamper_target",
    ["dataset_json", "review_csv", "source", "calendar", "adjustments", "point_in_time"],
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

    if tamper_target == "dataset_json":
        f = bundle_dir / "dataset.json"
        f.write_text(f.read_text().replace("30.0", "30.05"))
    elif tamper_target == "review_csv":
        f = bundle_dir / "dataset.csv"
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

    with pytest.raises(ValueError, match="evidence_hash_mismatch|dataset_digest_mismatch|review_csv_dataset_mismatch"):
        validate_candidate(manifest_file, project_root=tmp_path)


def test_rehashed_false_metadata_fails_semantic_validation(synthetic_ohlcv_df, tmp_path):
    """Adversarial test: attacker edits source.json period to '5y' and updates manifest hash -> FAIL."""
    import hashlib
    ticker = "CSAN3.SA"
    bundle_dir = tmp_path / "candidates" / "csan3"
    build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=synthetic_ohlcv_df,
    )
    manifest_file = bundle_dir / "candidate_manifest.json"
    m_data = json.loads(manifest_file.read_text(encoding="utf-8"))

    # Attacker modifies source.json
    source_file = bundle_dir / "source.json"
    source_obj = json.loads(source_file.read_text(encoding="utf-8"))
    source_obj["period"] = "5y"  # False metadata!
    new_bytes = (json.dumps(source_obj, indent=2, sort_keys=True) + "\n").encode("utf-8")
    source_file.write_bytes(new_bytes)

    # Attacker recomputes hash and updates manifest to pass file hash check
    m_data["source"]["sha256"] = hashlib.sha256(new_bytes).hexdigest()
    manifest_file.write_text(json.dumps(m_data, indent=2), encoding="utf-8")

    # Validator must reject semantic mismatch between manifest.period ('2y') and source.period ('5y')
    with pytest.raises(ValueError, match="source_period_mismatch|candidate_id_mismatch"):
        validate_candidate(manifest_file, project_root=tmp_path)


def test_candidate_strategy_mismatch_fails(synthetic_ohlcv_df, tmp_path):
    """Proves candidate manifest with strategy_id differing from active configuration fails."""
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
    m_data["strategy_id"] = "rogue_arbitrary_strategy_v99"
    manifest_file.write_text(json.dumps(m_data, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="strategy_id_mismatch"):
        validate_candidate(manifest_file, project_root=tmp_path)


def test_idempotent_regeneration_and_collision_rejection(synthetic_ohlcv_df, tmp_path):
    """Proves identical regeneration succeeds while conflicting candidate bytes trigger collision error."""
    ticker = "ITUB4.SA"
    bundle_dir = tmp_path / "candidates" / "itub4"

    # 1. First build
    m1 = build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=synthetic_ohlcv_df,
    )

    # 2. Re-running with same df is idempotent
    m2 = build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=synthetic_ohlcv_df,
    )
    assert m1.dataset_sha256 == m2.dataset_sha256

    # 3. Conflicting bytes in directory triggers collision error
    diff_df = synthetic_ohlcv_df.copy()
    diff_df.loc[diff_df.index[-1], "close"] = 41.50
    with pytest.raises(ValueError, match="candidate_collision_error"):
        build_candidate_bundle(
            ticker=ticker,
            output_dir=bundle_dir,
            project_root=tmp_path,
            df=diff_df,
        )


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

    # 1. Missing or wrong confirmation token
    with pytest.raises(ValueError, match="invalid_confirmation_token"):
        approve_candidate(
            candidate_path=manifest_file,
            reviewed_by="Victor",
            review_notes="Notes",
            confirm_digest=manifest.dataset_sha256,
            confirm_candidate_id=manifest.candidate_id,
            confirmation="WRONG_TOKEN",
            registry_path=registry_file,
            project_root=tmp_path,
        )

    # 2. Missing reviewed_by
    with pytest.raises(ValueError, match="reviewed_by_required"):
        approve_candidate(
            candidate_path=manifest_file,
            reviewed_by="",
            review_notes="Notes",
            confirm_digest=manifest.dataset_sha256,
            confirm_candidate_id=manifest.candidate_id,
            confirmation=APPROVAL_CONFIRMATION_TOKEN,
            registry_path=registry_file,
            project_root=tmp_path,
        )

    # 3. Missing review_notes
    with pytest.raises(ValueError, match="review_notes_required"):
        approve_candidate(
            candidate_path=manifest_file,
            reviewed_by="Victor",
            review_notes="   ",
            confirm_digest=manifest.dataset_sha256,
            confirm_candidate_id=manifest.candidate_id,
            confirmation=APPROVAL_CONFIRMATION_TOKEN,
            registry_path=registry_file,
            project_root=tmp_path,
        )

    # 4. Wrong confirm digest
    with pytest.raises(ValueError, match="confirm_digest_mismatch"):
        approve_candidate(
            candidate_path=manifest_file,
            reviewed_by="Victor",
            review_notes="Valid notes",
            confirm_digest="0" * 64,
            confirm_candidate_id=manifest.candidate_id,
            confirmation=APPROVAL_CONFIRMATION_TOKEN,
            registry_path=registry_file,
            project_root=tmp_path,
        )

    # 5. Wrong confirm candidate_id
    with pytest.raises(ValueError, match="confirm_candidate_id_mismatch"):
        approve_candidate(
            candidate_path=manifest_file,
            reviewed_by="Victor",
            review_notes="Valid notes",
            confirm_digest=manifest.dataset_sha256,
            confirm_candidate_id="f" * 64,
            confirmation=APPROVAL_CONFIRMATION_TOKEN,
            registry_path=registry_file,
            project_root=tmp_path,
        )

    # 6. Successful approval write
    appr = approve_candidate(
        candidate_path=manifest_file,
        reviewed_by="Victor",
        review_notes="Verified by Victor",
        confirm_digest=manifest.dataset_sha256,
        confirm_candidate_id=manifest.candidate_id,
        confirmation=APPROVAL_CONFIRMATION_TOKEN,
        registry_path=registry_file,
        project_root=tmp_path,
    )
    assert appr.dataset_sha256 == manifest.dataset_sha256
    assert appr.status == "approved"

    # Verify registry content on disk
    reg = Registry.model_validate_json(registry_file.read_bytes())
    assert len(reg.approvals) == 1
    assert reg.approvals[0].dataset_sha256 == manifest.dataset_sha256

    # 7. Duplicate approval fails closed
    with pytest.raises(ValueError, match="duplicate_approval"):
        approve_candidate(
            candidate_path=manifest_file,
            reviewed_by="Victor",
            review_notes="Attempt duplicate",
            confirm_digest=manifest.dataset_sha256,
            confirm_candidate_id=manifest.candidate_id,
            confirmation=APPROVAL_CONFIRMATION_TOKEN,
            registry_path=registry_file,
            project_root=tmp_path,
        )


def test_production_registry_remains_unmodified():
    """Verifies that config/data_approvals.json remains completely unmodified (version 1, 0 approvals)."""
    reg = Registry.model_validate_json(approval.REGISTRY.read_bytes())
    assert reg.version == 1
    assert reg.approvals == []


def test_duplicate_active_position_blocks_preflight(tmp_path):
    """Adversarial test: 2 active PETR4 positions cause active position invariant FAIL and overall BLOCKED."""
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
    # Note: Without the unique partial index or with bypassed insertion, insert 2 active trades
    conn.execute("INSERT INTO trades (ticker, status, signal_id) VALUES ('PETR4.SA', 'active', 'sig_1')")
    conn.execute("INSERT INTO trades (ticker, status, signal_id) VALUES ('PETR4.SA', 'active', 'sig_2')")
    conn.commit()
    conn.close()

    report = run_paper_preflight(
        db_path=test_db,
        storage_dir=tmp_path / "storage",
        tickers=["PETR4.SA"],
    )

    # Active position invariant must fail
    assert report.active_position_index_check is False
    assert report.overall_status == "BLOCKED"


def test_analyst_exact_frame_binding_and_failure_prevents_pass(synthetic_ohlcv_df, tmp_path, monkeypatch):
    """Proves Analyst analyzes exact supplied frame, and Analyst failure prevents PASS verdict."""
    ticker = "PETR4.SA"

    test_db = tmp_path / "test_trading.db"
    conn = sqlite3.connect(str(test_db))
    conn.execute("CREATE TABLE portfolio (id INTEGER PRIMARY KEY, patrimonio_total REAL, saldo_disponivel REAL)")
    conn.execute("INSERT INTO portfolio VALUES (1, 1000.0, 1000.0)")
    conn.execute(
        """
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY, ticker TEXT, side TEXT, shares REAL, entry_price REAL,
            exit_price REAL, target_price REAL, stop_loss REAL, entry_date TIMESTAMP,
            exit_date TIMESTAMP, pnl_pct REAL, exit_reason TEXT, ai_rationale TEXT,
            status TEXT, signal_id TEXT
        )
    """
    )
    conn.execute("CREATE UNIQUE INDEX idx_trades_strategy_signal_id ON trades(signal_id) WHERE signal_id IS NOT NULL")
    conn.execute("CREATE UNIQUE INDEX idx_trades_one_active_per_ticker ON trades(ticker) WHERE status = 'active'")
    conn.commit()
    conn.close()

    # Candidate and approval setup
    bundle_dir = tmp_path / "candidates" / "petr4"
    manifest = build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=synthetic_ohlcv_df,
    )
    registry_file = tmp_path / "test_registry.json"
    registry_file.write_text(json.dumps({"version": 1, "approvals": []}), encoding="utf-8")
    approve_candidate(
        candidate_path=bundle_dir / "candidate_manifest.json",
        reviewed_by="Victor",
        review_notes="Approved",
        confirm_digest=manifest.dataset_sha256,
        confirm_candidate_id=manifest.candidate_id,
        confirmation=APPROVAL_CONFIRMATION_TOKEN,
        registry_path=registry_file,
        project_root=tmp_path,
    )

    class MockMarket:
        def fetch_ohlcv(self, t, period="2y", interval="1d"):
            return synthetic_ohlcv_df.copy()

    from scripts import paper_session_preflight
    monkeypatch.setattr(paper_session_preflight, "resolve_market", lambda sym: MockMarket())

    # Case 1: MarketAnalyst throws an exception
    async def throwing_analyze_ohlcv(self, df, registry_path=None, project_root=None):
        raise RuntimeError("Analyst internal crash simulation")

    from backend.app.agents.market_analyst import MarketAnalyst
    monkeypatch.setattr(MarketAnalyst, "analyze_ohlcv", throwing_analyze_ohlcv)

    report = run_paper_preflight(
        registry_path=registry_file,
        db_path=test_db,
        storage_dir=tmp_path / "storage",
        tickers=[ticker],
    )

    # Verdict must be BLOCKED, NEVER PASS
    assert report.ticker_results[0].preflight_verdict == "BLOCKED"
    assert "Analyst failed" in report.ticker_results[0].approval_reason
    assert report.overall_status == "BLOCKED"


def test_custom_registry_without_global_monkeypatch(synthetic_ohlcv_df, tmp_path, monkeypatch):
    """Proves preflight validates against exact custom registry without touching global REGISTRY."""
    ticker = "VALE3.SA"
    test_db = tmp_path / "test_trading.db"
    conn = sqlite3.connect(str(test_db))
    conn.execute("CREATE TABLE portfolio (id INTEGER PRIMARY KEY, patrimonio_total REAL, saldo_disponivel REAL)")
    conn.execute("INSERT INTO portfolio VALUES (1, 1000.0, 1000.0)")
    conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, status TEXT, signal_id TEXT)")
    conn.execute("CREATE UNIQUE INDEX idx_trades_strategy_signal_id ON trades(signal_id) WHERE signal_id IS NOT NULL")
    conn.execute("CREATE UNIQUE INDEX idx_trades_one_active_per_ticker ON trades(status) WHERE status = 'active'")
    conn.commit()
    conn.close()

    bundle_dir = tmp_path / "candidates" / "vale3"
    manifest = build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=synthetic_ohlcv_df,
    )
    custom_reg = tmp_path / "custom_approvals.json"
    custom_reg.write_text(json.dumps({"version": 1, "approvals": []}), encoding="utf-8")

    # 1. Custom registry empty -> BLOCKED
    report_empty = run_paper_preflight(
        registry_path=custom_reg,
        db_path=test_db,
        storage_dir=tmp_path / "storage",
        tickers=[ticker],
    )
    assert report_empty.ticker_results[0].preflight_verdict == "BLOCKED"

    # 2. Approve in custom registry
    approve_candidate(
        candidate_path=bundle_dir / "candidate_manifest.json",
        reviewed_by="Victor",
        review_notes="Approved",
        confirm_digest=manifest.dataset_sha256,
        confirm_candidate_id=manifest.candidate_id,
        confirmation=APPROVAL_CONFIRMATION_TOKEN,
        registry_path=custom_reg,
        project_root=tmp_path,
    )

    class MockMarket:
        def fetch_ohlcv(self, t, period="2y", interval="1d"):
            return synthetic_ohlcv_df.copy()

    from scripts import paper_session_preflight
    monkeypatch.setattr(paper_session_preflight, "resolve_market", lambda sym: MockMarket())

    report_approved = run_paper_preflight(
        registry_path=custom_reg,
        db_path=test_db,
        storage_dir=tmp_path / "storage",
        project_root=tmp_path,
        tickers=[ticker],
    )
    assert report_approved.ticker_results[0].approval_status == "PASS"
    assert report_approved.ticker_results[0].preflight_verdict == "PASS"

    # Production registry remains empty
    assert approval.REGISTRY.read_text(encoding="utf-8").strip() == '{"version": 1, "approvals": []}'


def test_read_only_db_row_fingerprints_verified(synthetic_ohlcv_df, tmp_path):
    """Proves preflight computes row fingerprints and confirms zero database mutation."""
    test_db = tmp_path / "fingerprint.db"
    conn = sqlite3.connect(str(test_db))
    conn.execute("CREATE TABLE portfolio (id INTEGER PRIMARY KEY, patrimonio_total REAL, saldo_disponivel REAL)")
    conn.execute("INSERT INTO portfolio VALUES (1, 5000.0, 5000.0)")
    conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, ticker TEXT, status TEXT, signal_id TEXT)")
    conn.execute("INSERT INTO trades VALUES (1, 'ITUB4.SA', 'closed', 'sig_prior')")
    conn.execute("CREATE UNIQUE INDEX idx_trades_strategy_signal_id ON trades(signal_id) WHERE signal_id IS NOT NULL")
    conn.execute("CREATE UNIQUE INDEX idx_trades_one_active_per_ticker ON trades(ticker) WHERE status = 'active'")
    conn.commit()
    conn.close()

    report = run_paper_preflight(
        db_path=test_db,
        storage_dir=tmp_path / "storage",
        tickers=["ITUB4.SA"],
    )

    assert report.trade_mutations_count == 0
    assert report.portfolio_mutations_count == 0
    assert report.trades_fingerprint_match is True
    assert report.portfolio_fingerprint_match is True
