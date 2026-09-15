"""Adversarial and boundary tests for PaperSessionRunner (NEXUS-002)."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from backend.app.agents.contracts import TypedSignal
from trading_bot.execution.paper_session import PaperSessionRunner


VALID_SHA256 = "0" * 64


@pytest.fixture(autouse=True)
def synthetic_approval(monkeypatch):
    from trading_bot.data.approval import Approval, Evidence
    ev = Evidence(path="synthetic.csv", sha256=VALID_SHA256)
    appr = Approval(
        dataset_sha256=VALID_SHA256,
        reviewed_by="nexus-tester",
        review_notes="synthetic fixture",
        status="approved",
        source=ev,
        calendar=ev,
        adjustments=ev,
        point_in_time=ev,
    )
    monkeypatch.setattr(
        "trading_bot.data.approval.require_dataset_approval_by_digest",
        lambda d: appr if d == VALID_SHA256 else (_ for _ in ()).throw(ValueError("data_approval_required"))
    )


def _init_paper_test_db(db_path: Path, initial_cash: float = 1000.0):
    conn = sqlite3.connect(str(db_path))
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
    cursor.execute(
        "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, margem_operavel, updated_at) "
        "VALUES (?, ?, 0.0, ?, ?)",
        (initial_cash, initial_cash, initial_cash, datetime.now(timezone.utc).isoformat())
    )
    cursor.execute(
        "CREATE UNIQUE INDEX idx_trades_strategy_signal_id ON trades(signal_id) WHERE signal_id IS NOT NULL"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX idx_trades_single_active ON trades(ticker) WHERE status = 'active'"
    )
    conn.commit()
    conn.close()


def test_paper_session_raw_malformed_signal_rejection(tmp_path):
    db_file = tmp_path / "paper.db"
    storage_dir = tmp_path / "sessions"
    _init_paper_test_db(db_file)

    mock_rm = MagicMock()
    mock_exec = MagicMock()

    runner = PaperSessionRunner(
        session_id="test_malformed",
        db_path=str(db_file),
        storage_dir=str(storage_dir),
        risk_manager_cls=mock_rm,
        executor_cls=mock_exec,
    )

    malformed_signals = [
        {"invalid": "dictionary"},
        {"ticker": "PETR4", "side": "BUY", "price": -10.0},  # Negative price
    ]
    report = runner.run_cycle(signals=malformed_signals)

    assert report.orders_rejected == 2
    assert report.orders_executed == 0
    mock_rm.assert_not_called()
    mock_exec.return_value.execute_order.assert_not_called()

    conn = sqlite3.connect(str(db_file))
    trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    pf = conn.execute("SELECT saldo_disponivel FROM portfolio").fetchone()[0]
    conn.close()
    assert trade_count == 0
    assert pf == 1000.0


def test_paper_session_hold_signal_not_executable(tmp_path):
    db_file = tmp_path / "paper.db"
    storage_dir = tmp_path / "sessions"
    _init_paper_test_db(db_file)

    mock_rm = MagicMock()
    mock_exec = MagicMock()

    runner = PaperSessionRunner(
        session_id="test_hold",
        db_path=str(db_file),
        storage_dir=str(storage_dir),
        risk_manager_cls=mock_rm,
        executor_cls=mock_exec,
    )

    hold_signal = {
        "ticker": "PETR4",
        "side": "HOLD",
        "price": 30.0,
        "target_price": 30.0,
        "stop_loss": 30.0,
        "reason": "Hold test",
        "generated_at": datetime.now(timezone.utc),
        "dataset_sha256": VALID_SHA256,
        "dataset_approved": True,
    }
    report = runner.run_cycle(signals=[hold_signal])

    assert report.orders_rejected == 1
    assert report.orders_executed == 0
    mock_rm.assert_not_called()
    mock_exec.return_value.execute_order.assert_not_called()


def test_paper_session_replay_idempotency_in_session_and_across_restarts(tmp_path, mock_circuit_breaker):
    db_file = tmp_path / "paper.db"
    storage_dir = tmp_path / "sessions"
    _init_paper_test_db(db_file)

    now = datetime.now(timezone.utc)
    signal = {
        "ticker": "PETR4",
        "side": "BUY",
        "price": 30.0,
        "target_price": 33.0,
        "stop_loss": 28.5,
        "reason": "Test breakout",
        "generated_at": now,
        "dataset_sha256": VALID_SHA256,
        "dataset_approved": True,
    }

    # 1. First run executes the order
    runner1 = PaperSessionRunner(session_id="session_1", db_path=str(db_file), storage_dir=str(storage_dir))
    rep1 = runner1.run_cycle(signals=[signal])
    assert rep1.orders_executed == 1
    assert rep1.orders_skipped == 0

    conn = sqlite3.connect(str(db_file))
    trade = conn.execute("SELECT ticker, signal_id, status FROM trades").fetchone()
    conn.close()
    assert trade[0] == "PETR4"
    assert trade[1].startswith("sig_")
    assert trade[2] == "active"

    # 2. Resend same signal in same session runner -> skipped
    rep2 = runner1.run_cycle(signals=[signal])
    assert rep2.orders_executed == 0
    assert rep2.orders_skipped == 1

    # 3. Simulate process restart / new session runner -> skipped via DB check
    runner2 = PaperSessionRunner(session_id="session_2", db_path=str(db_file), storage_dir=str(storage_dir))
    rep3 = runner2.run_cycle(signals=[signal])
    assert rep3.orders_executed == 0
    assert rep3.orders_skipped == 1

    conn = sqlite3.connect(str(db_file))
    trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()
    assert trade_count == 1
