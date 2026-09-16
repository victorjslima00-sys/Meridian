"""Adversarial and idempotency tests for ExecutorAgent and SQLite durable protection (NEXUS-002)."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import pytest

from backend.app.agents.contracts import (
    ApprovedExecutionIntent,
    ManualExecutionIntent,
    RiskDecision,
    TypedSignal,
)
from backend.app.agents.executor import ExecutorAgent
from backend.app.data.database import init_db


VALID_SHA256 = "0" * 64


@pytest.fixture(autouse=True)
def synthetic_approval(monkeypatch):
    from trading_bot.data.approval import Approval, Evidence, compute_candidate_id
    ev = Evidence(path="synthetic.csv", sha256=VALID_SHA256)
    c_id = compute_candidate_id(
        ticker="PETR4",
        strategy_id="donchian_breakout",
        intended_use="PAPER_TRADING",
        dataset_sha256=VALID_SHA256,
        collected_at_utc="2026-09-16T12:00:00Z",
        dataset_artifact_sha256=ev.sha256,
        review_csv_sha256=ev.sha256,
        source_sha256=ev.sha256,
        calendar_sha256=ev.sha256,
        adjustments_sha256=ev.sha256,
        point_in_time_sha256=ev.sha256,
    )
    appr = Approval(
        candidate_id=c_id,
        ticker="PETR4",
        strategy_id="donchian_breakout",
        intended_use="PAPER_TRADING",
        dataset_sha256=VALID_SHA256,
        collected_at_utc="2026-09-16T12:00:00Z",
        dataset_artifact=ev,
        review_csv=ev,
        source=ev,
        calendar=ev,
        adjustments=ev,
        point_in_time=ev,
        reviewed_by="nexus-tester",
        review_notes="synthetic fixture",
        status="approved",
    )
    monkeypatch.setattr(
        "trading_bot.data.approval.require_dataset_approval_by_digest",
        lambda d, *a, **kw: appr if d == VALID_SHA256 else (_ for _ in ()).throw(ValueError("data_approval_required"))
    )


def _create_isolated_db(db_path: Path, initial_cash: float = 1000.0):
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("""
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
    """)
    cursor.execute("""
        CREATE TABLE portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patrimonio_total REAL DEFAULT 0.0,
            saldo_disponivel REAL DEFAULT 0.0,
            em_posicoes REAL DEFAULT 0.0,
            margem_operavel REAL,
            updated_at TIMESTAMP
        )
    """)
    cursor.execute(
        "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, updated_at) VALUES (?, ?, 0.0, ?)",
        (initial_cash, initial_cash, datetime.now(timezone.utc).isoformat())
    )
    cursor.execute(
        "CREATE UNIQUE INDEX idx_trades_strategy_signal_id ON trades(signal_id) WHERE signal_id IS NOT NULL"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX idx_trades_single_active ON trades(ticker) WHERE status = 'active'"
    )
    conn.commit()
    conn.close()


def test_executor_rejects_raw_approved_true_without_valid_intent(tmp_path):
    db_file = tmp_path / "test.db"
    _create_isolated_db(db_file)
    executor = ExecutorAgent(db_path=str(db_file))

    res = executor.execute_order({"approved": True})
    assert res["status"] == "rejected"

    conn = sqlite3.connect(str(db_file))
    count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()
    assert count == 0


def _make_intent(
    ticker="PETR4",
    price=30.0,
    target_price=33.0,
    stop_loss=28.5,
    allocated_capital=150.0,
    generated_at=None,
    dataset_sha256=VALID_SHA256,
):
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)
    sig = TypedSignal(
        ticker=ticker,
        side="BUY",
        price=price,
        target_price=target_price,
        stop_loss=stop_loss,
        confidence=70,
        reason="Test breakout signal",
        generated_at=generated_at,
        dataset_sha256=dataset_sha256,
        dataset_approved=True,
    )
    dec = RiskDecision(
        signal_id=sig.signal_id,
        approved=True,
        allocated_capital=allocated_capital,
        target_price=target_price,
        stop_loss=stop_loss,
        reason="Risk approved",
        decision_timestamp=datetime.now(timezone.utc),
    )
    return ApprovedExecutionIntent(signal=sig, risk_decision=dec)


def test_executor_rejects_arbitrary_unbound_ids():
    """Directive 002-R1 Section 3: ApprovedExecutionIntent rejects arbitrary formatted IDs."""
    with pytest.raises(Exception):
        ApprovedExecutionIntent(
            signal_id="sig_" + "a" * 64,
            decision_id="risk_" + "b" * 64,
            ticker="PETR4",
            side="BUY",
            entry_price=30.0,
            allocated_capital=150.0,
            target_price=33.0,
            stop_loss=28.5,
            dataset_sha256=VALID_SHA256,
        )


def test_executor_rejects_signal_risk_mismatch(tmp_path):
    db_file = tmp_path / "test.db"
    _create_isolated_db(db_file)
    executor = ExecutorAgent(db_path=str(db_file))

    sig = TypedSignal(
        ticker="PETR4",
        side="BUY",
        price=30.0,
        target_price=33.0,
        stop_loss=28.5,
        reason="Signal A",
        dataset_sha256=VALID_SHA256,
        dataset_approved=True,
        generated_at=datetime.now(timezone.utc),
    )
    dec_other = RiskDecision(
        signal_id="sig_" + "f" * 64,
        approved=True,
        allocated_capital=100.0,
        target_price=33.0,
        stop_loss=28.5,
        reason="Decision for other signal",
        decision_timestamp=datetime.now(timezone.utc),
    )

    with pytest.raises(ValueError, match="does not match"):
        ApprovedExecutionIntent(signal=sig, risk_decision=dec_other)

    # Calling executor with arbitrary dict is rejected
    res = executor.execute_order({"approved": True, "signal_id": "sig_" + "1" * 64})
    assert res["status"] == "rejected"


def test_executor_executes_valid_approved_intent(tmp_path):
    db_file = tmp_path / "test.db"
    _create_isolated_db(db_file)
    executor = ExecutorAgent(db_path=str(db_file))

    intent = _make_intent(ticker="PETR4", price=30.0, allocated_capital=150.0)
    res = executor.execute_order(intent)
    assert res["status"] == "executed"
    assert res["shares"] == 5.0

    conn = sqlite3.connect(str(db_file))
    trade = conn.execute("SELECT ticker, side, shares, status, signal_id FROM trades").fetchone()
    conn.close()
    assert trade[0] == "PETR4"
    assert trade[1] == "BUY"
    assert trade[2] == 5.0
    assert trade[3] == "active"
    assert trade[4] == intent.signal_id


def test_executor_manual_intent_leaves_signal_id_null(tmp_path):
    db_file = tmp_path / "test.db"
    _create_isolated_db(db_file)
    executor = ExecutorAgent(db_path=str(db_file))

    intent = ManualExecutionIntent(
        ticker="VALE3",
        side="BUY",
        entry_price=60.0,
        allocated_capital=120.0,
        target_price=66.0,
        stop_loss=57.0,
        reason="Manual Scalper",
    )
    res = executor.execute_manual_order(intent)
    assert res["status"] == "executed"

    conn = sqlite3.connect(str(db_file))
    trade = conn.execute("SELECT ticker, signal_id, ai_rationale FROM trades WHERE ticker = 'VALE3'").fetchone()
    conn.close()
    assert trade[0] == "VALE3"
    assert trade[1] is None  # signal_id is NULL for manual trades!
    assert "Manual" in trade[2]


def test_replay_protection_same_signal_id_rejected_after_close(tmp_path):
    """REPLAY TEST: Same signal_id cannot open a second trade even after first is closed."""
    db_file = tmp_path / "test.db"
    _create_isolated_db(db_file)
    executor = ExecutorAgent(db_path=str(db_file))

    intent = _make_intent(ticker="PETR4", price=30.0, allocated_capital=150.0)
    signal_id = intent.signal_id

    # 1. First execution succeeds
    res1 = executor.execute_order(intent)
    assert res1["status"] == "executed"

    conn = sqlite3.connect(str(db_file))
    trade_id = conn.execute("SELECT id FROM trades WHERE signal_id = ?", (signal_id,)).fetchone()[0]
    conn.close()

    # 2. Close trade
    res_close = executor.close_order(trade_id, 33.0, reason="Take Profit hit")
    assert res_close["status"] == "closed"

    conn = sqlite3.connect(str(db_file))
    pf_before = conn.execute("SELECT saldo_disponivel, em_posicoes FROM portfolio ORDER BY id DESC LIMIT 1").fetchone()
    trades_count_before = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()
    assert trades_count_before == 1

    # 3. Resend the EXACT SAME signal_id in a new executor instance
    executor_new = ExecutorAgent(db_path=str(db_file))
    res2 = executor_new.execute_order(intent)
    assert res2["status"] == "skipped_existing_position"
    assert "idempotency" in res2["reason"].lower()

    # 4. Prove no new trade row and portfolio balances unchanged
    conn = sqlite3.connect(str(db_file))
    pf_after = conn.execute("SELECT saldo_disponivel, em_posicoes FROM portfolio ORDER BY id DESC LIMIT 1").fetchone()
    trades_count_after = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()
    assert trades_count_after == 1
    assert pf_after[0] == pf_before[0]
    assert pf_after[1] == pf_before[1]


def test_new_signal_for_same_ticker_succeeds_after_close(tmp_path):
    """NEW SIGNAL TEST: Legitimately different signal_id for same ticker succeeds."""
    db_file = tmp_path / "test.db"
    _create_isolated_db(db_file)
    executor = ExecutorAgent(db_path=str(db_file))

    # 1. First trade
    intent1 = _make_intent(ticker="PETR4", price=30.0, target_price=33.0, stop_loss=28.5)
    res1 = executor.execute_order(intent1)
    assert res1["status"] == "executed"

    conn = sqlite3.connect(str(db_file))
    trade_id = conn.execute("SELECT id FROM trades WHERE signal_id = ?", (intent1.signal_id,)).fetchone()[0]
    conn.close()

    # 2. Close first trade
    executor.close_order(trade_id, 33.0, reason="Take Profit")

    # 3. New second signal with DIFFERENT price/stop/target/generated_at
    intent2 = _make_intent(ticker="PETR4", price=31.0, target_price=34.0, stop_loss=29.5)
    assert intent2.signal_id != intent1.signal_id

    res2 = executor.execute_order(intent2)
    assert res2["status"] == "executed"

    conn = sqlite3.connect(str(db_file))
    trades = conn.execute("SELECT status, signal_id FROM trades ORDER BY id ASC").fetchall()
    conn.close()
    assert len(trades) == 2
    assert trades[0][0] == "closed"
    assert trades[0][1] == intent1.signal_id
    assert trades[1][0] == "active"
    assert trades[1][1] == intent2.signal_id


def test_sqlite_unique_index_integrity_error(tmp_path):
    """Direct SQL integrity test proving unique partial index on trades(signal_id)."""
    db_file = tmp_path / "test.db"
    _create_isolated_db(db_file)

    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "INSERT INTO trades (ticker, side, signal_id, status) VALUES ('PETR4', 'BUY', 'sig_dup', 'closed')"
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO trades (ticker, side, signal_id, status) VALUES ('PETR4', 'BUY', 'sig_dup', 'active')"
        )
    conn.close()


def test_database_init_db_detects_duplicate_signal_ids(tmp_path, monkeypatch):
    """Startup fail diagnostic if database contains duplicate non-null signal_ids."""
    db_file = tmp_path / "test_dup.db"
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, side TEXT, shares REAL, entry_price REAL,
            exit_price REAL, target_price REAL, stop_loss REAL,
            entry_date TIMESTAMP, exit_date TIMESTAMP, pnl_pct REAL,
            exit_reason TEXT, ai_rationale TEXT, status TEXT, signal_id TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patrimonio_total REAL, saldo_disponivel REAL, em_posicoes REAL, margem_operavel REAL, updated_at TIMESTAMP
        )
    """)
    cursor.execute("INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, updated_at) VALUES (100, 100, 0, ?)", (datetime.now(),))
    cursor.execute("INSERT INTO trades (ticker, side, signal_id, status) VALUES ('T1', 'BUY', 'sig_dup', 'closed')")
    cursor.execute("INSERT INTO trades (ticker, side, signal_id, status) VALUES ('T2', 'BUY', 'sig_dup', 'closed')")
    conn.commit()
    conn.close()

    monkeypatch.setattr("backend.app.data.database.DB_PATH", str(db_file))
    monkeypatch.setattr("backend.app.data.database.get_connection", lambda isolation_level=None: sqlite3.connect(str(db_file), isolation_level=isolation_level))

    with pytest.raises(RuntimeError, match="Startup failed: Database contains duplicate strategy signal_ids in trades"):
        init_db()
