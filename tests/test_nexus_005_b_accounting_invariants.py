"""
MERIDIAN — NEXUS-005-B INVARIANT & ACCOUNTING TEST SUITE
=========================================================
Covers required test matrix A through AD + Concurrency test (Section 16).
All tests execute against isolated temporary SQLite databases.
"""

import datetime
import math
import os
import sqlite3
import tempfile
import threading
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.agents.contracts import (
    ApprovedExecutionIntent,
    ManualExecutionIntent,
    RiskDecision,
    TypedSignal,
)
from backend.app.agents.executor import ExecutorAgent
from backend.app.data import database as db
from backend.app.data.accounting import (
    MONETARY_EPSILON,
    AccountingIntegrityError,
    PortfolioIntegrityError,
    compute_exit_accounting,
    validate_monetary_value,
    validate_portfolio_fields,
)
from backend.app import main
from tests.conftest import make_test_evidenced_quote, make_synthetic_approval


@pytest.fixture(autouse=True)
def petr4_approval(monkeypatch):
    """Synthetic authority for PETR4.SA in accounting invariant tests."""
    authority = make_synthetic_approval("PETR4.SA", "0" * 64)
    monkeypatch.setattr(
        "trading_bot.data.approval.require_dataset_approval_by_digest",
        lambda d, *a, **kw: authority if d == "0" * 64 else
        (_ for _ in ()).throw(ValueError("data_approval_required")),
    )


@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    orig_path = db.DB_PATH
    db.DB_PATH = path
    monkeypatch.setattr("backend.app.agents.executor.DB_PATH", path)
    try:
        yield path
    finally:
        db.DB_PATH = orig_path
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass


def _make_intent(
    ticker: str = "PETR4.SA",
    allocated: float = 100.0,
    price: float = 25.0,
    side: str = "BUY",
    digest: str = "0" * 64,
) -> ApprovedExecutionIntent:
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    appr = make_synthetic_approval(ticker, digest)
    target = price * 1.10 if side == "BUY" else price * 0.90
    stop = price * 0.90 if side == "BUY" else price * 1.10
    sig = TypedSignal(
        ticker=ticker,
        side=side,
        price=price,
        target_price=target,
        stop_loss=stop,
        confidence=80,
        reason="NEXUS-005-B test signal",
        dataset_sha256=appr.dataset_sha256,
        dataset_approved=True,
        generated_at=now_utc,
        strategy_id=appr.strategy_id,
        intended_use=appr.intended_use,
        candidate_id=appr.candidate_id,
    )
    dec = RiskDecision(
        signal_id=sig.signal_id,
        approved=True,
        allocated_capital=allocated,
        target_price=target,
        stop_loss=stop,
        reason="Approved by Risk Decision",
        decision_timestamp=now_utc,
    )
    quote = make_test_evidenced_quote(ticker, price)
    return ApprovedExecutionIntent(
        signal=sig,
        risk_decision=dec,
        execution_quote=quote,
    )


# ===========================================================================
# Test A & B & Physical SQLite Backstop (Section 3, 15A, 15B, 16)
# ===========================================================================

def test_a_new_db_initialization_exactly_one_portfolio_row(temp_db):
    """A. new DB initialization -> exactly one portfolio row."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    rows = conn.execute("SELECT id, patrimonio_total, saldo_disponivel, em_posicoes FROM portfolio").fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0][1] == 0.0
    assert rows[0][2] == 0.0
    assert rows[0][3] == 0.0


def test_b_two_concurrent_init_db_executions(temp_db):
    """B & Section 16. Two concurrent init_db executions -> exactly one authoritative row."""
    barrier = threading.Barrier(2)
    errors = []

    def _worker():
        try:
            barrier.wait(timeout=5)
            # Each worker uses the real init_db()
            db.init_db()
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=_worker)
    t2 = threading.Thread(target=_worker)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not t1.is_alive(), "Worker thread 1 timed out and is still alive"
    assert not t2.is_alive(), "Worker thread 2 timed out and is still alive"

    assert errors == [], f"Concurrent init_db raised unexpected errors: {errors}"

    conn = sqlite3.connect(temp_db)
    rows = conn.execute("SELECT id FROM portfolio").fetchall()
    conn.close()

    assert len(rows) == 1, f"Expected exactly 1 row, got {len(rows)}: {rows}"


def test_sqlite_physical_singleton_backstop_blocks_second_insert(temp_db):
    """Section 3: SQLite physical unique index backstop prevents second row."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    with pytest.raises(sqlite3.IntegrityError) as exc_info:
        conn.execute(
            "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes) VALUES (10.0, 10.0, 0.0)"
        )
    conn.close()
    assert "UNIQUE constraint failed" in str(exc_info.value)


# ===========================================================================
# Test C & D: Startup Migration & Validation (Section 4, 15C, 15D)
# ===========================================================================

def test_c_preexisting_db_with_two_portfolio_rows_startup_rejects(temp_db):
    """C. pre-existing DB with two portfolio rows -> startup rejects / integrity failure."""
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "CREATE TABLE portfolio (id INTEGER PRIMARY KEY AUTOINCREMENT, patrimonio_total REAL, "
        "saldo_disponivel REAL, em_posicoes REAL, margem_operavel REAL, updated_at TIMESTAMP)"
    )
    conn.execute("INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes) VALUES (100.0, 100.0, 0.0)")
    conn.execute("INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes) VALUES (200.0, 200.0, 0.0)")
    conn.commit()
    conn.close()

    with patch("backend.app.data.database._alerta_telegram_startup") as mock_alert:
        with pytest.raises(RuntimeError) as exc_info:
            db.init_db()
        assert "multiple portfolio rows" in str(exc_info.value).lower()
        mock_alert.assert_called_once()

    # Data must not be merged or deleted
    conn = sqlite3.connect(temp_db)
    cnt = conn.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]
    conn.close()
    assert cnt == 2


def test_d_single_valid_existing_portfolio_preserved(temp_db):
    """D. single valid existing portfolio -> preserved."""
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "CREATE TABLE portfolio (id INTEGER PRIMARY KEY AUTOINCREMENT, patrimonio_total REAL, "
        "saldo_disponivel REAL, em_posicoes REAL, margem_operavel REAL, updated_at TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, margem_operavel) "
        "VALUES (50000.0, 20000.0, 5000.0, 15000.0)"
    )
    conn.commit()
    conn.close()

    db.init_db()

    pf = db.get_portfolio()
    assert pf["patrimonio_total"] == 50000.0
    assert pf["saldo_disponivel"] == 20000.0
    assert pf["em_posicoes"] == 5000.0
    assert pf["margem_operavel"] == 15000.0
    assert pf["saldo_livre"] == 15000.0
    assert pf["saldo_operavel"] == 10000.0


# ===========================================================================
# Test E, F, G, H: Corrupt Single Portfolio State at Startup (Section 15E-H)
# ===========================================================================

@pytest.mark.parametrize("corrupt_col,val", [
    ("patrimonio_total", None),
    ("saldo_disponivel", None),
    ("em_posicoes", None),
])
def test_e_single_portfolio_null_required_financial_field_fails_closed(temp_db, corrupt_col, val):
    """E. single portfolio with NULL required financial field -> fail closed."""
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "CREATE TABLE portfolio (id INTEGER PRIMARY KEY AUTOINCREMENT, patrimonio_total REAL, "
        "saldo_disponivel REAL, em_posicoes REAL, margem_operavel REAL, updated_at TIMESTAMP)"
    )
    conn.execute(
        f"INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes) "
        f"VALUES ({'NULL' if corrupt_col == 'patrimonio_total' else 100.0}, "
        f"{'NULL' if corrupt_col == 'saldo_disponivel' else 100.0}, "
        f"{'NULL' if corrupt_col == 'em_posicoes' else 0.0})"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError) as exc_info:
        db.init_db()
    assert "corrupt financial state" in str(exc_info.value).lower()


def test_f_single_portfolio_negative_required_field_fails_closed(temp_db):
    """F. single portfolio with negative required field -> fail closed."""
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "CREATE TABLE portfolio (id INTEGER PRIMARY KEY AUTOINCREMENT, patrimonio_total REAL, "
        "saldo_disponivel REAL, em_posicoes REAL, margem_operavel REAL, updated_at TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes) "
        "VALUES (100.0, -50.0, 0.0)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError) as exc_info:
        db.init_db()
    assert "cannot be negative" in str(exc_info.value).lower()


def test_g_single_portfolio_pos_inf_fails_closed(temp_db):
    """G. +Inf portfolio field -> fail closed."""
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "CREATE TABLE portfolio (id INTEGER PRIMARY KEY AUTOINCREMENT, patrimonio_total REAL, "
        "saldo_disponivel REAL, em_posicoes REAL, margem_operavel REAL, updated_at TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes) "
        "VALUES (100.0, 1e999, 0.0)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError) as exc_info:
        db.init_db()
    assert "must be finite" in str(exc_info.value).lower()


def test_h_single_portfolio_neg_inf_fails_closed(temp_db):
    """H. -Inf portfolio field -> fail closed."""
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "CREATE TABLE portfolio (id INTEGER PRIMARY KEY AUTOINCREMENT, patrimonio_total REAL, "
        "saldo_disponivel REAL, em_posicoes REAL, margem_operavel REAL, updated_at TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes) "
        "VALUES (100.0, -1e999, 0.0)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError) as exc_info:
        db.init_db()
    assert "must be finite" in str(exc_info.value).lower()


# ===========================================================================
# Test I, J, K, L: Non-Finite & Bool Money Input Boundary (Section 6, 15I-L)
# ===========================================================================

@pytest.mark.parametrize("bad_val", [float("nan"), "nan", float("inf"), float("-inf"), True, False])
def test_i_j_k_l_non_finite_and_bool_python_boundary_rejected(temp_db, bad_val):
    """I, J, K, L. NaN / ±Inf / bool rejected before mutation in Python functions."""
    db.init_db()
    res_dep = db.depositar_no_disponivel(bad_val)
    assert res_dep["ok"] is False

    res_ret = db.retirar_do_disponivel(bad_val)
    assert res_ret["ok"] is False

    res_marg = db.set_margem_operavel(bad_val)
    assert res_marg["ok"] is False


def test_i_j_k_l_api_boundary_rejected(temp_db, monkeypatch):
    """I, J, K, L. NaN / ±Inf / bool rejected before mutation in FastAPI REST endpoints."""
    db.init_db()
    api_key = "test-secret-key-16-chars-min"
    monkeypatch.setenv("API_KEY", api_key)
    client = TestClient(main.app)
    headers = {"X-API-Key": api_key}

    for bad in [True, False, "nan", "inf", "-inf"]:
        r_dep = client.post("/api/portfolio/depositar", json={"valor": bad}, headers=headers)
        assert r_dep.status_code in (400, 422)

        r_ret = client.post("/api/portfolio/retirar", json={"valor": bad}, headers=headers)
        assert r_ret.status_code in (400, 422)

        r_mar = client.post("/api/portfolio/margem_operavel", json={"valor": bad}, headers=headers)
        assert r_mar.status_code in (400, 422)


# ===========================================================================
# Test M, N, O, P, Q, R: Domain Boundaries (Section 6, 15M-R)
# ===========================================================================

def test_m_deposit_less_equal_zero_rejected(temp_db):
    """M. deposit <= 0 -> reject."""
    db.init_db()
    assert db.depositar_no_disponivel(0.0)["ok"] is False
    assert db.depositar_no_disponivel(-10.0)["ok"] is False


def test_n_withdraw_less_equal_zero_rejected(temp_db):
    """N. withdraw <= 0 -> reject."""
    db.init_db()
    assert db.retirar_do_disponivel(0.0)["ok"] is False
    assert db.retirar_do_disponivel(-5.0)["ok"] is False


def test_o_margin_negative_rejected(temp_db):
    """O. margin < 0 -> reject."""
    db.init_db()
    assert db.set_margem_operavel(-0.01)["ok"] is False


def test_p_margin_zero_valid(temp_db):
    """P. margin == 0 -> valid (freezes new allocations)."""
    db.init_db()
    res = db.set_margem_operavel(0.0)
    assert res["ok"] is True
    pf = db.get_portfolio()
    assert pf["margem_operavel"] == 0.0
    assert pf["saldo_operavel"] == 0.0


def test_q_withdraw_greater_than_saldo_livre_rejected(temp_db):
    """Q. withdraw > saldo_livre -> reject / zero mutation."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=500.0, saldo_disponivel=200.0, em_posicoes=150.0")
    conn.commit()
    conn.close()

    # Saldo livre = 50.0. Attempting to withdraw 50.01 must fail.
    res = db.retirar_do_disponivel(50.01)
    assert res["ok"] is False

    pf = db.get_portfolio()
    assert pf["patrimonio_total"] == 500.0
    assert pf["saldo_disponivel"] == 200.0
    assert pf["em_posicoes"] == 150.0


def test_r_deposit_greater_than_patrimonio_total_rejected(temp_db):
    """R. deposit > patrimonio_total -> reject / zero mutation."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=100.0, saldo_disponivel=50.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    res = db.depositar_no_disponivel(100.01)
    assert res["ok"] is False

    pf = db.get_portfolio()
    assert pf["patrimonio_total"] == 100.0
    assert pf["saldo_disponivel"] == 50.0


# ===========================================================================
# Test S & T: Entry Accounting Validation & Rollback (Section 9, 15S, 15T)
# ===========================================================================

def test_s_entry_with_corrupt_portfolio_state_rejects_and_zero_trade_mutation(temp_db):
    """S. entry with corrupt portfolio state -> reject / zero trade mutation."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    # em_posicoes > saldo_disponivel (accounting breach)
    conn.execute("UPDATE portfolio SET saldo_disponivel=100.0, em_posicoes=150.0")
    conn.commit()
    conn.close()

    executor = ExecutorAgent(db_path=temp_db)
    intent = _make_intent(allocated=50.0, price=25.0)

    res = executor.execute_order(intent)
    assert res["status"] == "rejected"
    assert "portfolio integrity failure" in res["reason"].lower()

    # Verify zero trade mutation
    conn = sqlite3.connect(temp_db)
    trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()
    assert trades == 0


def test_t_entry_with_non_finite_persisted_portfolio_state_rejects_zero_mutation(temp_db):
    """T. entry with non-finite persisted portfolio state -> reject / zero mutation."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET saldo_disponivel=1e999, em_posicoes=0.0")
    conn.commit()
    conn.close()

    executor = ExecutorAgent(db_path=temp_db)
    intent = _make_intent(allocated=50.0, price=25.0)

    res = executor.execute_order(intent)
    assert res["status"] == "rejected"

    conn = sqlite3.connect(temp_db)
    trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()
    assert trades == 0


# ===========================================================================
# Test U, V, W, X, Y, Z: Exit Accounting & Epsilon Handling (Section 10, 15U-Z)
# ===========================================================================

def test_u_v_w_close_when_em_posicoes_less_than_allocation_rejects_and_rolls_back(temp_db):
    """
    U. close when em_posicoes < original_allocation by material amount -> reject + rollback
    V. on U, trade status remains active
    W. on U, portfolio remains byte/semantically unchanged
    """
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET saldo_disponivel=200.0, em_posicoes=20.0")
    # Active trade has cost basis = 2.0 * 25.0 = 50.0 BRL, but em_posicoes is only 20.0 (deficit of 30.0 BRL)
    conn.execute(
        "INSERT INTO trades (id, ticker, side, shares, entry_price, status) VALUES (1, 'PETR4.SA', 'BUY', 2.0, 25.0, 'active')"
    )
    conn.commit()
    conn.close()

    executor = ExecutorAgent(db_path=temp_db)
    ev = make_test_evidenced_quote("PETR4.SA", 30.0)
    res = executor.close_order(1, 30.0, "Take Profit", evidence=ev)

    assert res["status"] == "rejected"
    assert "em_posicoes" in res["reason"] and "original_allocation" in res["reason"]

    # V: trade status remains active
    conn = sqlite3.connect(temp_db)
    trade = conn.execute("SELECT status, exit_price FROM trades WHERE id = 1").fetchone()
    assert trade[0] == "active"
    assert trade[1] is None

    # W: portfolio remains semantically unchanged
    pf = conn.execute("SELECT saldo_disponivel, em_posicoes FROM portfolio WHERE id = 1").fetchone()
    conn.close()
    assert pf[0] == 200.0
    assert pf[1] == 20.0


def test_x_close_with_tiny_rounding_residual_within_epsilon_normalizes_to_zero(temp_db):
    """X. close with tiny rounding residual within canonical epsilon -> permitted normalization to zero."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    # Trade cost basis: 1.0 * 50.0 = 50.0
    # em_posicoes has a 5e-5 micro-residual (0.00005 < 1e-4 epsilon)
    conn.execute("UPDATE portfolio SET saldo_disponivel=100.0, em_posicoes=50.00005")
    conn.execute(
        "INSERT INTO trades (id, ticker, side, shares, entry_price, status) VALUES (1, 'PETR4.SA', 'BUY', 1.0, 50.0, 'active')"
    )
    conn.commit()
    conn.close()

    executor = ExecutorAgent(db_path=temp_db)
    ev = make_test_evidenced_quote("PETR4.SA", 55.0)
    res = executor.close_order(1, 55.0, "Take Profit", evidence=ev)

    assert res["status"] == "closed"
    conn = sqlite3.connect(temp_db)
    pf = conn.execute("SELECT saldo_disponivel, em_posicoes FROM portfolio WHERE id = 1").fetchone()
    conn.close()

    # em_posicoes must be cleanly normalized to exact 0.0
    assert pf[1] == 0.0
    assert pf[0] == 105.0


def test_y_close_with_null_nan_inf_shares_rejects_and_rolls_back(temp_db):
    """Y. close with NULL/NaN/Inf shares -> reject / rollback."""
    db.init_db()
    for bad_shares in [None, "nan", -1.0, 0.0]:
        conn = sqlite3.connect(temp_db)
        conn.execute("DELETE FROM trades")
        conn.execute("UPDATE portfolio SET saldo_disponivel=100.0, em_posicoes=50.0")
        conn.execute(
            "INSERT INTO trades (id, ticker, side, shares, entry_price, status) VALUES (1, 'PETR4.SA', 'BUY', ?, 50.0, 'active')",
            (bad_shares,),
        )
        conn.commit()
        conn.close()

        executor = ExecutorAgent(db_path=temp_db)
        ev = make_test_evidenced_quote("PETR4.SA", 55.0)
        res = executor.close_order(1, 55.0, "Take Profit", evidence=ev)

        assert res["status"] == "rejected"
        assert "corrupt trade" in res["reason"].lower()

        conn = sqlite3.connect(temp_db)
        st = conn.execute("SELECT status FROM trades WHERE id = 1").fetchone()[0]
        conn.close()
        assert st == "active"


def test_z_close_with_invalid_entry_price_rejects_and_rolls_back(temp_db):
    """Z. close with invalid entry_price -> reject / rollback."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET saldo_disponivel=100.0, em_posicoes=50.0")
    conn.execute(
        "INSERT INTO trades (id, ticker, side, shares, entry_price, status) VALUES (1, 'PETR4.SA', 'BUY', 1.0, -25.0, 'active')"
    )
    conn.commit()
    conn.close()

    executor = ExecutorAgent(db_path=temp_db)
    ev = make_test_evidenced_quote("PETR4.SA", 30.0)
    res = executor.close_order(1, 30.0, "Take Profit", evidence=ev)

    assert res["status"] == "rejected"
    assert "corrupt trade" in res["reason"].lower()

    conn = sqlite3.connect(temp_db)
    st = conn.execute("SELECT status FROM trades WHERE id = 1").fetchone()[0]
    conn.close()
    assert st == "active"


# ===========================================================================
# Test AA & AB: Conservation & Entry/Exit Round Trip (Section 11, 15AA, 15AB)
# ===========================================================================

def test_aa_deposit_withdraw_conservation(temp_db):
    """AA. deposit/withdraw conservation -> exact accounting invariant."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=1000.0, saldo_disponivel=500.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    initial_total = 1500.0

    # Human deposit moves 200 from patrimonio_total -> saldo_disponivel
    res_dep = db.depositar_no_disponivel(200.0)
    assert res_dep["ok"] is True
    assert res_dep["patrimonio_total"] == 800.0
    assert res_dep["saldo_disponivel"] == 700.0
    assert (res_dep["patrimonio_total"] + res_dep["saldo_disponivel"]) == initial_total

    # Human withdrawal moves 300 from saldo_disponivel -> patrimonio_total
    res_ret = db.retirar_do_disponivel(300.0)
    assert res_ret["ok"] is True
    assert res_ret["patrimonio_total"] == 1100.0
    assert res_ret["saldo_disponivel"] == 400.0
    assert (res_ret["patrimonio_total"] + res_ret["saldo_disponivel"]) == initial_total


def test_ab_normal_entry_exit_round_trip_accounting(temp_db):
    """AB. normal entry/exit round trip -> correct saldo/em_posicoes/P&L behavior."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=1000.0, saldo_disponivel=500.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    executor = ExecutorAgent(db_path=temp_db)

    # 1. Entry: allocate 200 BRL at 20 BRL/share (10 shares)
    intent = _make_intent(ticker="PETR4.SA", allocated=200.0, price=20.0)
    res_entry = executor.execute_order(intent)
    assert res_entry["status"] == "executed"
    assert res_entry["shares"] == 10.0

    pf_entry = db.get_portfolio()
    assert pf_entry["saldo_disponivel"] == 500.0
    assert pf_entry["em_posicoes"] == 200.0
    assert pf_entry["saldo_livre"] == 300.0

    conn = sqlite3.connect(temp_db)
    trade_id = conn.execute("SELECT id FROM trades WHERE status = 'active'").fetchone()[0]
    conn.close()

    # 2. Exit with profit: exit price 25 BRL/share (+25% PnL)
    # Gross return: 10 * 25 = 250 BRL. Realized PnL: +50 BRL.
    # New saldo_disponivel = 500 - 200 + 250 = 550 BRL.
    # New em_posicoes = 200 - 200 = 0.0 BRL.
    ev_exit = make_test_evidenced_quote("PETR4.SA", 25.0)
    res_exit = executor.close_order(trade_id, 25.0, "Take Profit", evidence=ev_exit)
    assert res_exit["status"] == "closed"
    assert res_exit["pnl_pct"] == 25.0

    pf_exit = db.get_portfolio()
    assert pf_exit["saldo_disponivel"] == 550.0
    assert pf_exit["em_posicoes"] == 0.0
    assert pf_exit["saldo_livre"] == 550.0


# ===========================================================================
# Test AC & AD: Portfolio Read & Equity Computation (Section 7, 13, 15AC, 15AD)
# ===========================================================================

def test_ac_get_portfolio_missing_authoritative_row_fails_closed(temp_db):
    """AC. get_portfolio on missing authoritative row after initialized schema -> fail closed."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("DELETE FROM portfolio")
    conn.commit()
    conn.close()

    with pytest.raises(PortfolioIntegrityError) as exc_info:
        db.get_portfolio()
    assert "missing" in str(exc_info.value).lower() or "no portfolio row" in str(exc_info.value).lower()


def test_ad_compute_current_equity_corrupt_portfolio_or_trade_fails_closed(temp_db):
    """AD. compute_current_equity with corrupt portfolio/trade numeric state -> fail closed, never fabricated zero."""
    db.init_db()

    # 1. Corrupt portfolio state (negative saldo)
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET saldo_disponivel=-10.0")
    conn.commit()
    conn.close()

    with pytest.raises((PortfolioIntegrityError, AccountingIntegrityError)):
        db.compute_current_equity()

    # Restore valid portfolio
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET saldo_disponivel=100.0, em_posicoes=50.0")
    # 2. Corrupt active trade shares
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, status) VALUES ('PETR4.SA', 'BUY', -5.0, 10.0, 'active')"
    )
    conn.commit()
    conn.close()

    with patch("backend.app.data.feed.get_current_price", return_value=12.0):
        with pytest.raises(AccountingIntegrityError) as exc_info:
            db.compute_current_equity()
        assert "shares" in str(exc_info.value).lower()

    # 3. Corrupt active trade entry_price
    conn = sqlite3.connect(temp_db)
    conn.execute("DELETE FROM trades")
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, status) VALUES ('PETR4.SA', 'BUY', 5.0, -10.0, 'active')"
    )
    conn.commit()
    conn.close()

    with patch("backend.app.data.feed.get_current_price", return_value=12.0):
        with pytest.raises(AccountingIntegrityError) as exc_info:
            db.compute_current_equity()
        assert "entry_price" in str(exc_info.value).lower()


# ===========================================================================
# Concurrency & TradeRequest Hardening Tests
# ===========================================================================

def test_trade_request_quantity_rejects_bool_and_non_finite():
    """TradeRequest rejects bool, NaN, Inf, and non-positive quantity."""
    from backend.app.main import TradeRequest
    from pydantic import ValidationError

    for invalid_qty in (True, False, float("nan"), float("inf"), float("-inf"), 0, -5.0, None):
        with pytest.raises((ValidationError, ValueError)):
            TradeRequest(ticker="PETR4.SA", side="BUY", quantity=invalid_qty)


def test_concurrent_entry_orders_prevent_overallocation(temp_db, monkeypatch):
    """Two concurrent entry orders with combined cost > saldo_livre must not over-allocate."""
    db.init_db()

    # Seed portfolio with exactly 150.0 saldo_disponivel, 0.0 em_posicoes
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "UPDATE portfolio SET patrimonio_total=500.0, saldo_disponivel=150.0, em_posicoes=0.0"
    )
    conn.commit()
    conn.close()

    # Set up synthetic authority for VALE3.SA as well
    appr_vale = make_synthetic_approval("VALE3.SA", "1" * 64)
    orig_lookup = monkeypatch
    monkeypatch.setattr(
        "trading_bot.data.approval.require_dataset_approval_by_digest",
        lambda d, *a, **kw: appr_vale if d == "1" * 64 else
        make_synthetic_approval("PETR4.SA", "0" * 64) if d == "0" * 64 else
        (_ for _ in ()).throw(ValueError("data_approval_required")),
    )

    intent_petr = _make_intent(ticker="PETR4.SA", allocated=100.0, price=25.0)
    intent_vale = _make_intent(ticker="VALE3.SA", allocated=100.0, price=50.0, digest="1" * 64)

    from backend.app.markets.b3_session import AutonomousSessionAuthority, B3DayType, B3SessionPhase, override_session_authority
    import contextvars

    auth = AutonomousSessionAuthority(override_fn=lambda dt: (True, "OK", B3DayType.NORMAL_TRADING_DAY, B3SessionPhase.CONTINUOUS))

    barrier = threading.Barrier(2)
    results = [None, None]
    worker_errors = []

    def _worker(idx, intent):
        try:
            barrier.wait(timeout=5)
            agent = ExecutorAgent(db_path=temp_db, session_authority=auth)
            results[idx] = agent.execute_order(intent)
        except Exception as e:
            worker_errors.append((idx, e))

    with override_session_authority(auth):
        ctx1 = contextvars.copy_context()
        ctx2 = contextvars.copy_context()
        t1 = threading.Thread(target=ctx1.run, args=(_worker, 0, intent_petr))
        t2 = threading.Thread(target=ctx2.run, args=(_worker, 1, intent_vale))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

    assert not t1.is_alive(), "Worker thread 1 timed out and is still alive"
    assert not t2.is_alive(), "Worker thread 2 timed out and is still alive"
    assert not worker_errors, f"Worker thread encountered unhandled exceptions: {worker_errors}"

    statuses = [r["status"] for r in results]
    # Exactly one should succeed, one must be rejected for insufficient capital
    assert "executed" in statuses, f"Expected at least one execution, got {results}"
    assert "rejected" in statuses, f"Expected one rejection due to capital limits, got {results}"

    conn = sqlite3.connect(temp_db)
    em_pos = conn.execute("SELECT em_posicoes FROM portfolio").fetchone()[0]
    trades = conn.execute("SELECT ticker, shares FROM trades WHERE status='active'").fetchall()
    conn.close()

    assert em_pos == 100.0, f"em_posicoes should be exactly 100.0, got {em_pos}"
    assert len(trades) == 1, f"Expected exactly 1 active trade, got {len(trades)}"


# ===========================================================================
# NEXUS-005-B-R1: Long-Only Enforcement & Fail-Closed SELL / Short Regressions
# Directive Sections 8 & 9
# ===========================================================================

def test_r1_a_manual_buy_opening_preserved(temp_db, monkeypatch):
    """A. manual BUY opening -> existing behavior preserved."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=1000.0, saldo_disponivel=1000.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    api_key = "test-secret-key-16-chars-min"
    monkeypatch.setenv("API_KEY", api_key)
    async def _mock_gate():
        return True, []
    monkeypatch.setattr("backend.app.main._avaliar_portao_de_entradas", _mock_gate)
    monkeypatch.setattr("backend.app.main.get_current_price", lambda ticker: 25.0)

    client = TestClient(main.app)
    headers = {"X-API-Key": api_key}
    resp = client.post("/api/trades/execute", json={"ticker": "PETR4.SA", "side": "BUY", "quantity": 10.0}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "executed"
    assert data["shares"] == 10.0

    conn = sqlite3.connect(temp_db)
    trades = conn.execute("SELECT ticker, side, shares, status FROM trades WHERE status='active'").fetchall()
    em_pos = conn.execute("SELECT em_posicoes FROM portfolio").fetchone()[0]
    conn.close()
    assert len(trades) == 1
    assert trades[0][1] == "BUY"
    assert em_pos == 250.0


def test_r1_b_c_d_manual_sell_opening_rejected_zero_mutation(temp_db, monkeypatch):
    """B, C, D. manual SELL opening -> rejected, 0 trades inserted, portfolio unchanged."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=1000.0, saldo_disponivel=1000.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    api_key = "test-secret-key-16-chars-min"
    monkeypatch.setenv("API_KEY", api_key)

    client = TestClient(main.app)
    headers = {"X-API-Key": api_key}
    resp = client.post("/api/trades/execute", json={"ticker": "PETR4.SA", "side": "SELL", "quantity": 10.0}, headers=headers)
    assert resp.status_code == 400
    assert "SHORT_SELL_EXECUTION_NOT_SUPPORTED" in resp.json()["detail"]

    # C. 0 trades inserted
    conn = sqlite3.connect(temp_db)
    trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    # D. portfolio unchanged
    pf_row = conn.execute("SELECT patrimonio_total, saldo_disponivel, em_posicoes FROM portfolio").fetchone()
    conn.close()
    assert trade_count == 0
    assert pf_row[0] == 1000.0
    assert pf_row[1] == 1000.0
    assert pf_row[2] == 0.0


def test_r1_e_approved_execution_intent_buy_preserved(temp_db):
    """E. ApprovedExecutionIntent BUY -> existing behavior preserved."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=1000.0, saldo_disponivel=1000.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    from backend.app.markets.b3_session import AutonomousSessionAuthority, B3DayType, B3SessionPhase, override_session_authority
    auth = AutonomousSessionAuthority(override_fn=lambda dt: (True, "OK", B3DayType.NORMAL_TRADING_DAY, B3SessionPhase.CONTINUOUS))

    with override_session_authority(auth):
        intent = _make_intent(ticker="PETR4.SA", allocated=250.0, price=25.0, side="BUY")
        executor = ExecutorAgent(db_path=temp_db, session_authority=auth)
        res = executor.execute_order(intent)

    assert res["status"] == "executed"
    assert res["shares"] == 10.0

    conn = sqlite3.connect(temp_db)
    trade = conn.execute("SELECT side, status FROM trades WHERE status='active'").fetchone()
    em_pos = conn.execute("SELECT em_posicoes FROM portfolio").fetchone()[0]
    conn.close()
    assert trade == ("BUY", "active")
    assert em_pos == 250.0


def test_r1_f_g_h_approved_execution_intent_sell_rejected_zero_mutation(temp_db):
    """F, G, H. ApprovedExecutionIntent SELL -> executor rejects, zero trade mutation, portfolio unchanged."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=1000.0, saldo_disponivel=1000.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    from backend.app.markets.b3_session import AutonomousSessionAuthority, B3DayType, B3SessionPhase, override_session_authority
    auth = AutonomousSessionAuthority(override_fn=lambda dt: (True, "OK", B3DayType.NORMAL_TRADING_DAY, B3SessionPhase.CONTINUOUS))

    with override_session_authority(auth):
        intent = _make_intent(ticker="PETR4.SA", allocated=250.0, price=25.0, side="SELL")
        executor = ExecutorAgent(db_path=temp_db, session_authority=auth)
        res = executor.execute_order(intent)

    # F. executor rejects
    assert res["status"] == "rejected"
    assert "SHORT_SELL_EXECUTION_NOT_SUPPORTED" in res["reason"]

    # G. zero trade mutation
    conn = sqlite3.connect(temp_db)
    trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    # H. portfolio unchanged
    pf_row = conn.execute("SELECT patrimonio_total, saldo_disponivel, em_posicoes FROM portfolio").fetchone()
    conn.close()
    assert trade_count == 0
    assert pf_row[0] == 1000.0
    assert pf_row[1] == 1000.0
    assert pf_row[2] == 0.0


def test_r1_i_compute_exit_accounting_side_sell_raises_accounting_integrity_error():
    """I. compute_exit_accounting(side="SELL") -> AccountingIntegrityError."""
    with pytest.raises(AccountingIntegrityError) as exc_info:
        compute_exit_accounting(
            saldo_disponivel=1000.0,
            em_posicoes=200.0,
            shares=10.0,
            entry_price=20.0,
            exit_price=30.0,
            side="SELL",
        )
    assert "SHORT_SELL_EXECUTION_NOT_SUPPORTED" in str(exc_info.value)


def test_r1_j_k_l_m_persisted_active_sell_close_order_fails_closed(temp_db):
    """J, K, L, M. persisted active SELL + close_order -> fail closed, trade active, exit_price None, pf unchanged."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=1000.0, saldo_disponivel=800.0, em_posicoes=200.0")
    conn.execute(
        """
        INSERT INTO trades (ticker, side, shares, entry_price, status)
        VALUES ('PETR4.SA', 'SELL', 10.0, 20.0, 'active')
        """
    )
    conn.commit()
    trade_id = conn.execute("SELECT id FROM trades WHERE status='active'").fetchone()[0]
    conn.close()

    from backend.app.markets.b3_session import AutonomousSessionAuthority, B3DayType, B3SessionPhase, override_session_authority
    auth = AutonomousSessionAuthority(override_fn=lambda dt: (True, "OK", B3DayType.NORMAL_TRADING_DAY, B3SessionPhase.CONTINUOUS))

    quote = make_test_evidenced_quote("PETR4.SA", 30.0)
    executor = ExecutorAgent(db_path=temp_db, session_authority=auth)

    with override_session_authority(auth):
        res = executor.close_order(trade_id, current_price=30.0, reason="take_profit", evidence=quote)

    # J. fail closed with remediation-required reason
    assert res["status"] == "rejected"
    assert "UNSUPPORTED_ACTIVE_TRADE_SIDE" in res["reason"]

    conn = sqlite3.connect(temp_db)
    row = conn.execute("SELECT status, exit_price FROM trades WHERE id=?", (trade_id,)).fetchone()
    pf = conn.execute("SELECT patrimonio_total, saldo_disponivel, em_posicoes FROM portfolio").fetchone()
    conn.close()

    # K. trade remains active
    assert row[0] == "active"
    # L. exit_price remains unchanged (None)
    assert row[1] is None
    # M. portfolio remains unchanged
    assert pf[0] == 1000.0
    assert pf[1] == 800.0
    assert pf[2] == 200.0


def test_r1_n_unsupported_arbitrary_opening_side_deterministic_rejection(temp_db, monkeypatch):
    """N. unsupported arbitrary opening side -> deterministic rejection."""
    db.init_db()
    api_key = "test-secret-key-16-chars-min"
    monkeypatch.setenv("API_KEY", api_key)
    client = TestClient(main.app)
    headers = {"X-API-Key": api_key}

    # API boundary
    resp = client.post("/api/trades/execute", json={"ticker": "PETR4.SA", "side": "HOLD", "quantity": 10.0}, headers=headers)
    assert resp.status_code == 400
    assert "UNSUPPORTED_SIDE_EXECUTION" in resp.json()["detail"]

    # Executor direct boundary with manual SELL
    manual = ManualExecutionIntent(
        ticker="PETR4.SA",
        side="SELL",
        entry_price=20.0,
        allocated_capital=200.0,
        target_price=18.0,
        stop_loss=22.0,
        reason="Arbitrary side test",
        operator="test_operator",
    )
    executor = ExecutorAgent(db_path=temp_db)
    res = executor.execute_manual_order(manual)
    assert res["status"] == "rejected"
    assert "SHORT_SELL_EXECUTION_NOT_SUPPORTED" in res["reason"]

    # Executor direct boundary with non-intent object
    res_bad = executor.execute_manual_order("not_an_intent")
    assert res_bad["status"] == "rejected"


def test_r1_o_buy_entry_exit_roundtrip_correct(temp_db):
    """O. BUY entry -> exit roundtrip remains correct."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=1000.0, saldo_disponivel=1000.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    from backend.app.markets.b3_session import AutonomousSessionAuthority, B3DayType, B3SessionPhase, override_session_authority
    auth = AutonomousSessionAuthority(override_fn=lambda dt: (True, "OK", B3DayType.NORMAL_TRADING_DAY, B3SessionPhase.CONTINUOUS))

    with override_session_authority(auth):
        intent = _make_intent(ticker="PETR4.SA", allocated=200.0, price=20.0, side="BUY")
        executor = ExecutorAgent(db_path=temp_db, session_authority=auth)
        res_entry = executor.execute_order(intent)
        assert res_entry["status"] == "executed"

        conn = sqlite3.connect(temp_db)
        trade_id = conn.execute("SELECT id FROM trades WHERE status='active'").fetchone()[0]
        conn.close()

        quote = make_test_evidenced_quote("PETR4.SA", 25.0)
        res_exit = executor.close_order(trade_id, current_price=25.0, reason="take_profit", evidence=quote)
        assert res_exit["status"] == "closed"

    pf = db.get_portfolio()
    assert pf["em_posicoes"] == 0.0
    # Entry 10 shares @ 20 = 200. Exit 10 shares @ 25 = 250. PnL = +50. Saldo disponivel = 1000 - 200 + 250 = 1050.
    assert pf["saldo_disponivel"] == 1050.0


def test_r1_argus_exact_reproduction_case_1_losing_short_fails_closed(temp_db):
    """Section 9: CASE 1 - SELL shares=10, entry=20, exit=30 MUST NOT produce +100 BRL cash."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=1000.0, saldo_disponivel=800.0, em_posicoes=200.0")
    conn.execute(
        """
        INSERT INTO trades (ticker, side, shares, entry_price, status)
        VALUES ('PETR4.SA', 'SELL', 10.0, 20.0, 'active')
        """
    )
    conn.commit()
    trade_id = conn.execute("SELECT id FROM trades WHERE status='active'").fetchone()[0]
    conn.close()

    from backend.app.markets.b3_session import AutonomousSessionAuthority, B3DayType, B3SessionPhase, override_session_authority
    auth = AutonomousSessionAuthority(override_fn=lambda dt: (True, "OK", B3DayType.NORMAL_TRADING_DAY, B3SessionPhase.CONTINUOUS))

    quote = make_test_evidenced_quote("PETR4.SA", 30.0)
    executor = ExecutorAgent(db_path=temp_db, session_authority=auth)

    with override_session_authority(auth):
        res = executor.close_order(trade_id, current_price=30.0, reason="stop_loss", evidence=quote)

    assert res["status"] == "rejected"
    assert "UNSUPPORTED_ACTIVE_TRADE_SIDE" in res["reason"]

    # Invariant: cash MUST NOT increase to 900.0 (800 + 100 fabricated cash)
    pf = db.get_portfolio()
    assert pf["saldo_disponivel"] == 800.0
    assert pf["em_posicoes"] == 200.0

    # Also directly verify compute_exit_accounting fails closed
    with pytest.raises(AccountingIntegrityError):
        compute_exit_accounting(
            saldo_disponivel=800.0,
            em_posicoes=200.0,
            shares=10.0,
            entry_price=20.0,
            exit_price=30.0,
            side="SELL",
        )


def test_r1_argus_exact_reproduction_case_2_winning_short_fails_closed(temp_db):
    """Section 9: CASE 2 - SELL shares=10, entry=20, exit=10 MUST NOT produce -100 BRL cash."""
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=1000.0, saldo_disponivel=800.0, em_posicoes=200.0")
    conn.execute(
        """
        INSERT INTO trades (ticker, side, shares, entry_price, status)
        VALUES ('PETR4.SA', 'SELL', 10.0, 20.0, 'active')
        """
    )
    conn.commit()
    trade_id = conn.execute("SELECT id FROM trades WHERE status='active'").fetchone()[0]
    conn.close()

    from backend.app.markets.b3_session import AutonomousSessionAuthority, B3DayType, B3SessionPhase, override_session_authority
    auth = AutonomousSessionAuthority(override_fn=lambda dt: (True, "OK", B3DayType.NORMAL_TRADING_DAY, B3SessionPhase.CONTINUOUS))

    quote = make_test_evidenced_quote("PETR4.SA", 10.0)
    executor = ExecutorAgent(db_path=temp_db, session_authority=auth)

    with override_session_authority(auth):
        res = executor.close_order(trade_id, current_price=10.0, reason="take_profit", evidence=quote)

    assert res["status"] == "rejected"
    assert "UNSUPPORTED_ACTIVE_TRADE_SIDE" in res["reason"]

    # Invariant: cash MUST NOT decrease to 700.0 (800 - 100 inverted cash)
    pf = db.get_portfolio()
    assert pf["saldo_disponivel"] == 800.0
    assert pf["em_posicoes"] == 200.0

    # Also directly verify compute_exit_accounting fails closed
    with pytest.raises(AccountingIntegrityError):
        compute_exit_accounting(
            saldo_disponivel=800.0,
            em_posicoes=200.0,
            shares=10.0,
            entry_price=20.0,
            exit_price=10.0,
            side="SELL",
        )


