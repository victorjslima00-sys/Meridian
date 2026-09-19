"""
Persistent Tests for NEXUS-005-C1-R2: Canonical PaperSession Equity & Portfolio Authority.
Validates:
A. PaperSession uses canonical get_portfolio semantics
B. Multiple portfolio rows -> PaperSession fails closed
C. saldo_disponivel < em_posicoes materially -> no max(0) masking -> fail closed
D. reference equity None -> ORDER_REJECTED
E. reference equity NaN/+Inf/-Inf/<=0 -> ORDER_REJECTED
F. PaperSession does NOT use patrimonio_total as reference equity
G. PaperSession does NOT fallback to saldo_operavel + em_posicoes
H. RiskManager receives explicit reference_equity
I. TypeError compatibility fallback removed
J. Normal Paper BUY path still works under synthetic approved test authority
"""
from __future__ import annotations

import datetime
import math
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from backend.app.agents.risk_manager import RiskManager
from backend.app.data.accounting import PortfolioIntegrityError
from backend.app.data.database import compute_current_equity, get_portfolio
from tests.conftest import make_synthetic_approval, make_test_evidenced_quote, synthetic_identity_kwargs as _authority
from trading_bot.execution.paper_session import PaperSessionRunner


@pytest.fixture(autouse=True)
def local_approvals(monkeypatch):
    """Synthetic authorities bound to distinct digests."""
    authorities = {
        "0" * 64: make_synthetic_approval("PETR4", "0" * 64),
        "1" * 64: make_synthetic_approval("VALE3", "1" * 64),
    }
    monkeypatch.setattr(
        "trading_bot.data.approval.require_dataset_approval_by_digest",
        lambda d, *a, **kw: authorities[d] if d in authorities else (_ for _ in ()).throw(ValueError("data_approval_required")),
    )


@pytest.fixture(autouse=True)
def mock_feed_quotes():
    """Hermetic mock feed for evidenced quotes and current prices."""
    def _quote_side_effect(ticker, *args, **kwargs):
        t_clean = ticker.replace(".SA", "").upper()
        if t_clean == "PETR4":
            return make_test_evidenced_quote("PETR4", 30.0)
        elif t_clean == "VALE3":
            return make_test_evidenced_quote("VALE3", 60.0)
        return make_test_evidenced_quote(t_clean, 50.0)

    def _price_side_effect(ticker, *args, **kwargs):
        return _quote_side_effect(ticker).price

    with patch("backend.app.data.feed.get_evidenced_quote", side_effect=_quote_side_effect), \
         patch("backend.app.data.feed.get_current_price", side_effect=_price_side_effect):
        yield


@pytest.fixture
def mock_circuit_breaker():
    breaker = MagicMock()
    breaker.can_trade.return_value = True
    with patch("trading_bot.risk.circuit_breaker.CircuitBreaker.from_config", return_value=breaker):
        yield breaker


def _init_test_db(
    db_path: Path,
    patrimonio_total: float | None = None,
    saldo_disponivel: float | None = None,
    em_posicoes: float = 0.0,
    margem_operavel: float | None = None,
    initial_cash: float = 1000.0,
) -> None:
    pat = initial_cash if patrimonio_total is None else patrimonio_total
    disp = initial_cash if saldo_disponivel is None else saldo_disponivel
    marg = initial_cash if margem_operavel is None else margem_operavel

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, side TEXT, shares REAL, entry_price REAL,
            exit_price REAL, target_price REAL, stop_loss REAL,
            entry_date TIMESTAMP, exit_date TIMESTAMP,
            pnl_pct REAL, exit_reason TEXT, ai_rationale TEXT, status TEXT, signal_id TEXT
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_one_active_per_ticker
        ON trades (ticker) WHERE status = 'active'
    """)
    conn.execute("""
        CREATE TABLE portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patrimonio_total REAL DEFAULT 0.0,
            saldo_disponivel REAL DEFAULT 0.0,
            em_posicoes REAL DEFAULT 0.0,
            margem_operavel REAL,
            updated_at TIMESTAMP
        )
    """)
    conn.execute(
        "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, margem_operavel, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (pat, disp, em_posicoes, marg, datetime.datetime.now(datetime.timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def _make_signal(ticker="PETR4", price=30.0, target_price=33.0, stop_loss=28.5, digest="0" * 64):
    return {
        "ticker": ticker,
        "signal": "BUY",
        "current_price": price,
        "target_price": target_price,
        "stop_loss": stop_loss,
        "confidence": 80,
        "reason": "Donchian 20d Breakout",
        "dataset_sha256": digest,
        "dataset_approved": True,
        "generated_at": datetime.datetime.now(datetime.timezone.utc),
        **_authority(digest, ticker),
    }


# ===========================================================================
# Test A: PaperSession uses canonical get_portfolio semantics
# ===========================================================================
def test_a_paper_session_uses_canonical_get_portfolio_semantics(tmp_path):
    db_file = tmp_path / "paper_test.db"
    _init_test_db(db_file, patrimonio_total=1200.0, saldo_disponivel=1000.0, em_posicoes=200.0, margem_operavel=800.0)
    runner = PaperSessionRunner(session_id="session_test_a", db_path=str(db_file))

    pf_state = runner.get_portfolio_state()
    canonical_pf = get_portfolio(db_path=str(db_file))

    assert pf_state == canonical_pf
    assert pf_state["saldo_livre"] == 800.0
    assert pf_state["saldo_operavel"] == 600.0
    assert pf_state["patrimonio_total"] == 1200.0
    assert pf_state["saldo_disponivel"] == 1000.0
    assert pf_state["em_posicoes"] == 200.0


# ===========================================================================
# Test B: Multiple portfolio rows -> PaperSession fails closed
# ===========================================================================
def test_b_multiple_portfolio_rows_fails_closed(tmp_path, mock_circuit_breaker):
    db_file = tmp_path / "paper_test.db"
    storage_dir = tmp_path / "paper_sessions"
    _init_test_db(db_file, 1000.0, 1000.0, 0.0)

    # Insert a corrupting second row
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, updated_at) "
        "VALUES (2000.0, 2000.0, 0.0, ?)",
        (datetime.datetime.now(datetime.timezone.utc).isoformat(),),
    )
    conn.commit()
    conn.close()

    runner = PaperSessionRunner(session_id="session_test_b", db_path=str(db_file), storage_dir=str(storage_dir))

    # Calling get_portfolio_state directly must fail closed
    with pytest.raises(PortfolioIntegrityError) as exc_info:
        runner.get_portfolio_state()
    assert "multiple portfolio rows detected" in str(exc_info.value)

    # run_cycle must fail closed without executing orders
    sig = _make_signal()
    with pytest.raises(PortfolioIntegrityError):
        runner.run_cycle(signals=[sig])

    # No trade executed in DB
    conn = sqlite3.connect(db_file)
    trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()
    assert trade_count == 0


# ===========================================================================
# Test C: saldo_disponivel < em_posicoes materially -> no max(0) masking -> fail closed
# ===========================================================================
def test_c_saldo_disponivel_less_than_em_posicoes_fails_closed_no_max0_masking(tmp_path, mock_circuit_breaker):
    db_file = tmp_path / "paper_test.db"
    storage_dir = tmp_path / "paper_sessions"
    # Material deficit: 500.0 < 1000.0
    _init_test_db(db_file, patrimonio_total=1000.0, saldo_disponivel=500.0, em_posicoes=1000.0)

    runner = PaperSessionRunner(session_id="session_test_c", db_path=str(db_file), storage_dir=str(storage_dir))

    with pytest.raises(PortfolioIntegrityError) as exc_info:
        runner.get_portfolio_state()
    assert "Accounting invariant failure: saldo_disponivel (500.0) < em_posicoes (1000.0)" in str(exc_info.value)

    sig = _make_signal()
    with pytest.raises(PortfolioIntegrityError):
        runner.run_cycle(signals=[sig])


# ===========================================================================
# Test D: reference equity None -> ORDER_REJECTED
# ===========================================================================
def test_d_reference_equity_none_order_rejected(tmp_path, mock_circuit_breaker):
    db_file = tmp_path / "paper_test.db"
    storage_dir = tmp_path / "paper_sessions"
    _init_test_db(db_file, initial_cash=1000.0)

    runner = PaperSessionRunner(session_id="session_test_d", db_path=str(db_file), storage_dir=str(storage_dir))
    sig = _make_signal()

    with patch("trading_bot.execution.paper_session.compute_current_equity", return_value=None):
        report = runner.run_cycle(signals=[sig])

    assert report.orders_executed == 0
    assert report.orders_rejected == 1
    assert report.reconciliation_ok is True

    journal_path = storage_dir / "session_test_d.jsonl"
    lines = [line.strip() for line in journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any("Reference equity is unavailable (None)" in l for l in lines)

    conn = sqlite3.connect(db_file)
    trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()
    assert trade_count == 0


# ===========================================================================
# Test E: reference equity NaN / +Inf / -Inf / <= 0 -> ORDER_REJECTED
# ===========================================================================
@pytest.mark.parametrize("bad_equity", [float("nan"), float("inf"), float("-inf"), 0.0, -500.0])
def test_e_reference_equity_non_finite_or_non_positive_order_rejected(tmp_path, mock_circuit_breaker, bad_equity):
    db_file = tmp_path / f"paper_test_e_{bad_equity}.db"
    storage_dir = tmp_path / "paper_sessions"
    _init_test_db(db_file, initial_cash=1000.0)

    runner = PaperSessionRunner(session_id=f"session_test_e_{bad_equity}", db_path=str(db_file), storage_dir=str(storage_dir))
    sig = _make_signal()

    with patch("trading_bot.execution.paper_session.compute_current_equity", return_value=bad_equity):
        report = runner.run_cycle(signals=[sig])

    assert report.orders_executed == 0
    assert report.orders_rejected == 1
    assert report.reconciliation_ok is True


# ===========================================================================
# Test F: PaperSession does NOT use patrimonio_total as reference equity
# ===========================================================================
def test_f_paper_session_does_not_use_patrimonio_total_as_reference_equity(tmp_path, mock_circuit_breaker):
    """
    Directive Example:
      patrimonio_total = 100
      saldo_disponivel = 1000
      em_posicoes = 0
      canonical current equity = 1000

    With max_position_fraction = 10%:
      expected sizing reference is 1000 (allocating R$ 100.00),
      NOT 100 (which would allocate only R$ 10.00).
    """
    db_file = tmp_path / "paper_test_f.db"
    storage_dir = tmp_path / "paper_sessions"
    _init_test_db(db_file, patrimonio_total=100.0, saldo_disponivel=1000.0, em_posicoes=0.0, margem_operavel=1000.0)

    runner = PaperSessionRunner(session_id="session_test_f", db_path=str(db_file), storage_dir=str(storage_dir))
    sig = _make_signal(price=30.0, target_price=33.0, stop_loss=28.5)

    report = runner.run_cycle(signals=[sig])
    assert report.orders_executed == 1

    conn = sqlite3.connect(db_file)
    trade = conn.execute("SELECT shares, entry_price FROM trades WHERE status = 'active'").fetchone()
    conn.close()

    assert trade is not None
    allocated_capital = round(trade[0] * trade[1], 2)
    # Expected allocation is 10% of 1000.0 = R$ 100.00, not 10% of 100.0 = R$ 10.00
    assert allocated_capital == pytest.approx(100.0, abs=0.01)


# ===========================================================================
# Test G: PaperSession does NOT fallback to saldo_operavel + em_posicoes
# ===========================================================================
def test_g_paper_session_does_not_fallback_to_saldo_operavel_plus_em_posicoes(tmp_path, mock_circuit_breaker):
    db_file = tmp_path / "paper_test_g.db"
    storage_dir = tmp_path / "paper_sessions"
    _init_test_db(db_file, initial_cash=1000.0)

    runner = PaperSessionRunner(session_id="session_test_g", db_path=str(db_file), storage_dir=str(storage_dir))
    sig = _make_signal()

    # compute_current_equity fails (raises exception or returns None)
    with patch("trading_bot.execution.paper_session.compute_current_equity", side_effect=RuntimeError("feed down")):
        report = runner.run_cycle(signals=[sig])

    # Must reject, NEVER fall back to saldo_operavel + em_posicoes
    assert report.orders_executed == 0
    assert report.orders_rejected == 1

    conn = sqlite3.connect(db_file)
    count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()
    assert count == 0


# ===========================================================================
# Test H: RiskManager receives explicit reference_equity
# ===========================================================================
def test_h_risk_manager_receives_explicit_reference_equity(tmp_path, mock_circuit_breaker):
    db_file = tmp_path / "paper_test_h.db"
    storage_dir = tmp_path / "paper_sessions"
    _init_test_db(db_file, initial_cash=1500.0)

    captured_kwargs = {}

    class SpyRiskManager(RiskManager):
        def __init__(self, *args, **kwargs):
            captured_kwargs.update(kwargs)
            super().__init__(*args, **kwargs)

    runner = PaperSessionRunner(
        session_id="session_test_h",
        db_path=str(db_file),
        storage_dir=str(storage_dir),
        risk_manager_cls=SpyRiskManager,
    )
    sig = _make_signal()

    report = runner.run_cycle(signals=[sig])
    assert report.orders_executed == 1

    assert "reference_equity" in captured_kwargs
    assert captured_kwargs["reference_equity"] == pytest.approx(1500.0)


# ===========================================================================
# Test I: TypeError compatibility fallback removed
# ===========================================================================
def test_i_type_error_compatibility_fallback_removed(tmp_path, mock_circuit_breaker):
    """
    A legacy RiskManager that rejects reference_equity keyword argument
    MUST raise TypeError. No silent compatibility fallback.
    """
    db_file = tmp_path / "paper_test_i.db"
    storage_dir = tmp_path / "paper_sessions"
    _init_test_db(db_file, initial_cash=1000.0)

    class LegacyRiskManager:
        def __init__(self, saldo_livre, em_posicoes=0.0):
            self.saldo_livre = saldo_livre
            self.em_posicoes = em_posicoes

    runner = PaperSessionRunner(
        session_id="session_test_i",
        db_path=str(db_file),
        storage_dir=str(storage_dir),
        risk_manager_cls=LegacyRiskManager,
    )
    sig = _make_signal()

    with pytest.raises(TypeError) as exc_info:
        runner.run_cycle(signals=[sig])
    assert "unexpected keyword argument 'reference_equity'" in str(exc_info.value)


# ===========================================================================
# Test J: Normal Paper BUY path still works under synthetic approved authority
# ===========================================================================
def test_j_normal_paper_buy_path_under_synthetic_approved_authority(tmp_path, mock_circuit_breaker):
    db_file = tmp_path / "paper_test_j.db"
    storage_dir = tmp_path / "paper_sessions"
    _init_test_db(db_file, initial_cash=1000.0)

    runner = PaperSessionRunner(session_id="session_test_j", db_path=str(db_file), storage_dir=str(storage_dir))
    sig = _make_signal(ticker="PETR4", price=30.0, target_price=33.0, stop_loss=28.5)

    report = runner.run_cycle(signals=[sig])

    assert report.orders_executed == 1
    assert report.orders_skipped == 0
    assert report.orders_rejected == 0
    assert report.reconciliation_ok is True
    assert report.discrepancies == []
    assert report.real_broker_calls is None
    assert report.real_broker_calls_verification == "UNVERIFIED"
    assert report.status == "RECONCILED"

    conn = sqlite3.connect(db_file)
    trade = conn.execute("SELECT ticker, side, shares, entry_price, status FROM trades WHERE status = 'active'").fetchone()
    assert trade is not None
    assert trade[0] == "PETR4"
    assert trade[1] == "BUY"
    assert trade[4] == "active"
    conn.close()
