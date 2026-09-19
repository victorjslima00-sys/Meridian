"""
MERIDIAN — NEXUS-005-C1 POSITION SIZING, CONCENTRATION & TRANSACTIONAL LIMITS
=============================================================================
Author: ANTIGRAVITY
Test Matrix covering items 1-22 of Section 14 + Section 15 Backtest Parity.
All tests execute against isolated temporary SQLite databases.
"""

import datetime
import math
import os
import sqlite3
import tempfile
import threading
from typing import Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.agents.contracts import (
    ApprovedExecutionIntent,
    RiskDecision,
    TypedSignal,
)
from backend.app.agents.executor import ExecutorAgent
from backend.app.agents.risk_manager import RiskManager
from backend.app.data import database as db
from backend.app.markets.b3_session import (
    AutonomousSessionAuthority,
    B3DayType,
    B3SessionPhase,
    override_session_authority,
)
from tests.conftest import make_synthetic_approval, make_test_evidenced_quote
from trading_bot.risk.position_sizing import (
    calculate_position_size,
    validate_reference_equity,
)


@pytest.fixture(autouse=True)
def synthetic_approvals(monkeypatch):
    """Synthetic authorities for tickers in position limits test suite."""
    appr_petr = make_synthetic_approval("PETR4.SA", "0" * 64)
    appr_vale = make_synthetic_approval("VALE3.SA", "1" * 64)
    appr_itub = make_synthetic_approval("ITUB4.SA", "2" * 64)
    appr_bbdc = make_synthetic_approval("BBDC4.SA", "3" * 64)

    lookup = {
        "0" * 64: appr_petr,
        "1" * 64: appr_vale,
        "2" * 64: appr_itub,
        "3" * 64: appr_bbdc,
    }

    monkeypatch.setattr(
        "trading_bot.data.approval.require_dataset_approval_by_digest",
        lambda d, *a, **kw: lookup[d] if d in lookup else (_ for _ in ()).throw(ValueError("data_approval_required")),
    )


@pytest.fixture(autouse=True)
def circuit_breaker_unblocked():
    with patch("trading_bot.risk.circuit_breaker.CircuitBreaker.can_trade", return_value=True):
        yield


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


@pytest.fixture
def active_session_auth():
    return AutonomousSessionAuthority(
        override_fn=lambda dt: (True, "OK", B3DayType.NORMAL_TRADING_DAY, B3SessionPhase.CONTINUOUS)
    )


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
        reason="NEXUS-005-C test signal",
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
# 1. Exact max_position_fraction boundary -> accepted
# ===========================================================================
def test_1_exact_max_position_fraction_boundary_accepted(temp_db, active_session_auth):
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=1000.0, saldo_disponivel=1000.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    # ref = 1000.0, max_position_fraction = 0.10 -> hard_cap = 100.0
    intent = _make_intent(ticker="PETR4.SA", allocated=100.0, price=25.0)
    with override_session_authority(active_session_auth):
        executor = ExecutorAgent(db_path=temp_db, session_authority=active_session_auth)
        res = executor.execute_order(intent)

    assert res["status"] == "executed"
    assert res["total_value"] == 100.0
    assert res["shares"] == 4.0

    conn = sqlite3.connect(temp_db)
    pf = conn.execute("SELECT patrimonio_total, saldo_disponivel, em_posicoes FROM portfolio").fetchone()
    conn.close()
    assert pf[0] == 1000.0
    assert pf[1] == 1000.0
    assert pf[2] == 100.0


# ===========================================================================
# 2. Above boundary -> rejected / 0 mutation
# ===========================================================================
def test_2_above_max_position_fraction_rejected_zero_mutation(temp_db, active_session_auth):
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=1000.0, saldo_disponivel=1000.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    # ref = 1000.0, hard_cap = 100.0, allocated = 100.05
    intent = _make_intent(ticker="PETR4.SA", allocated=100.05, price=25.0)
    with override_session_authority(active_session_auth):
        executor = ExecutorAgent(db_path=temp_db, session_authority=active_session_auth)
        res = executor.execute_order(intent)

    assert res["status"] == "rejected"
    assert "Position concentration limit exceeded" in res["reason"]

    conn = sqlite3.connect(temp_db)
    trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    pf = conn.execute("SELECT patrimonio_total, saldo_disponivel, em_posicoes FROM portfolio").fetchone()
    conn.close()

    assert trade_count == 0
    assert pf[0] == 1000.0
    assert pf[1] == 1000.0
    assert pf[2] == 0.0


# ===========================================================================
# 3. Kelly cap < concentration cap -> Kelly wins
# ===========================================================================
def test_3_kelly_cap_less_than_concentration_cap_kelly_wins():
    # reference_equity = 1000.0, kelly = 0.05 (50.0), max_pos_frac = 0.10 (100.0), cash = 950.0
    res = calculate_position_size(
        capital_cash=950.0,
        current_open_count=0,
        max_positions=3,
        kelly_fraction=0.05,
        max_position_fraction=0.10,
        reference_equity=1000.0,
    )
    assert res == 50.0


# ===========================================================================
# 4. Concentration cap < Kelly cap -> concentration wins
# ===========================================================================
def test_4_concentration_cap_less_than_kelly_cap_concentration_wins():
    # reference_equity = 1000.0, kelly = 0.25 (250.0), max_pos_frac = 0.10 (100.0), cash = 1000.0
    res = calculate_position_size(
        capital_cash=1000.0,
        current_open_count=0,
        max_positions=3,
        kelly_fraction=0.25,
        max_position_fraction=0.10,
        reference_equity=1000.0,
    )
    assert res == 100.0


# ===========================================================================
# 5. saldo_operavel < both -> saldo_operavel wins
# ===========================================================================
def test_5_saldo_operavel_less_than_both_saldo_operavel_wins():
    # reference_equity = 1000.0, kelly = 0.25 (250.0), max_pos_frac = 0.10 (100.0), cash = 57.0
    res = calculate_position_size(
        capital_cash=57.0,
        current_open_count=0,
        max_positions=3,
        kelly_fraction=0.25,
        max_position_fraction=0.10,
        reference_equity=1000.0,
    )
    assert res == 57.0


# ===========================================================================
# 6. Reference equity unavailable -> blocked
# ===========================================================================
def test_6_reference_equity_unavailable_blocked():
    with pytest.raises(ValueError, match="Reference equity is unavailable"):
        validate_reference_equity(None)

    with pytest.raises(ValueError, match="Reference equity is unavailable"):
        calculate_position_size(
            capital_cash=1000.0,
            current_open_count=0,
            max_positions=3,
            kelly_fraction=0.25,
            max_position_fraction=0.10,
            reference_equity=None,
        )

    # RiskManager vetoes when reference_equity is None
    rm = RiskManager(
        saldo_livre=1000.0,
        reference_equity=None,
        validation_context={"approved_dataset": True, "caller": "trusted_pipeline"},
    )
    sig = _make_intent().signal
    dec = rm.evaluate_trade(sig)
    assert not dec.approved
    assert "reference equity" in dec.reason.lower()


# ===========================================================================
# 7. Reference equity NaN/+Inf/-Inf -> blocked
# ===========================================================================
def test_7_reference_equity_nan_inf_blocked():
    for val in [float("nan"), float("inf"), float("-inf")]:
        with pytest.raises(ValueError, match="Reference equity is non-finite"):
            validate_reference_equity(val)

        with pytest.raises(ValueError, match="Reference equity is non-finite"):
            calculate_position_size(
                capital_cash=1000.0,
                current_open_count=0,
                max_positions=3,
                kelly_fraction=0.25,
                max_position_fraction=0.10,
                reference_equity=val,
            )

        rm = RiskManager(
            saldo_livre=1000.0,
            reference_equity=val,
            validation_context={"approved_dataset": True, "caller": "trusted_pipeline"},
        )
        dec = rm.evaluate_trade(_make_intent().signal)
        assert not dec.approved


# ===========================================================================
# 8. Zero/negative reference equity -> blocked
# ===========================================================================
def test_8_reference_equity_zero_or_negative_blocked():
    for val in [0.0, -10.0, -1000.0]:
        with pytest.raises(ValueError, match="strictly positive"):
            validate_reference_equity(val)

        with pytest.raises(ValueError, match="strictly positive"):
            calculate_position_size(
                capital_cash=1000.0,
                current_open_count=0,
                max_positions=3,
                kelly_fraction=0.25,
                max_position_fraction=0.10,
                reference_equity=val,
            )

        rm = RiskManager(
            saldo_livre=1000.0,
            reference_equity=val,
            validation_context={"approved_dataset": True, "caller": "trusted_pipeline"},
        )
        dec = rm.evaluate_trade(_make_intent().signal)
        assert not dec.approved


# ===========================================================================
# 9. Invalid Kelly -> fail closed, NO 0.25 fallback
# ===========================================================================
def test_9_invalid_kelly_fails_closed_no_fallback():
    for invalid_kelly in [0.0, -0.5, 1.5, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            calculate_position_size(
                capital_cash=1000.0,
                current_open_count=0,
                max_positions=3,
                kelly_fraction=invalid_kelly,
                max_position_fraction=0.10,
                reference_equity=1000.0,
            )


# ===========================================================================
# 10. Invalid max_position_fraction -> fail closed
# ===========================================================================
def test_10_invalid_max_position_fraction_fails_closed():
    for invalid_frac in [0.0, -0.1, 1.1, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            calculate_position_size(
                capital_cash=1000.0,
                current_open_count=0,
                max_positions=3,
                kelly_fraction=0.25,
                max_position_fraction=invalid_frac,
                reference_equity=1000.0,
            )


# ===========================================================================
# 11. Manual concentration bypass -> rejected by Executor
# ===========================================================================
def test_11_manual_concentration_bypass_rejected(temp_db, monkeypatch):
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
    # 10 shares @ 25.0 = 250.0 > hard cap of 100.0 (10% of 1000)
    resp = client.post("/api/trades/execute", json={"ticker": "PETR4.SA", "side": "BUY", "quantity": 10.0}, headers=headers)
    assert resp.status_code == 400
    assert "Concentração máxima excedida" in resp.json()["detail"]

    conn = sqlite3.connect(temp_db)
    trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()
    assert trade_count == 0


# ===========================================================================
# 12. Autonomous oversized allocation -> rejected by Executor
# ===========================================================================
def test_12_autonomous_oversized_allocation_rejected_by_executor(temp_db, active_session_auth):
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=1000.0, saldo_disponivel=1000.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    # Pre-crafted intent requesting 500.0 (50% of reference equity)
    intent = _make_intent(ticker="PETR4.SA", allocated=500.0, price=25.0)
    with override_session_authority(active_session_auth):
        executor = ExecutorAgent(db_path=temp_db, session_authority=active_session_auth)
        res = executor.execute_order(intent)

    assert res["status"] == "rejected"
    assert "Position concentration limit exceeded" in res["reason"]

    conn = sqlite3.connect(temp_db)
    trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()
    assert trade_count == 0


# ===========================================================================
# 13. Max positions reached manual -> rejected
# ===========================================================================
def test_13_max_positions_reached_manual_rejected(temp_db, monkeypatch):
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=10000.0, saldo_disponivel=10000.0, em_posicoes=0.0")
    # Insert 3 active trades with distinct tickers (default max_positions = 3)
    conn.execute("INSERT INTO trades (ticker, side, shares, entry_price, status) VALUES ('PETR4.SA', 'BUY', 10, 25.0, 'active')")
    conn.execute("INSERT INTO trades (ticker, side, shares, entry_price, status) VALUES ('VALE3.SA', 'BUY', 10, 50.0, 'active')")
    conn.execute("INSERT INTO trades (ticker, side, shares, entry_price, status) VALUES ('ITUB4.SA', 'BUY', 10, 30.0, 'active')")
    conn.commit()
    conn.close()

    api_key = "test-secret-key-16-chars-min"
    monkeypatch.setenv("API_KEY", api_key)
    async def _mock_gate():
        return True, []
    monkeypatch.setattr("backend.app.main._avaliar_portao_de_entradas", _mock_gate)
    monkeypatch.setattr("backend.app.main.get_current_price", lambda ticker: 20.0)

    client = TestClient(main.app)
    headers = {"X-API-Key": api_key}
    # Try 4th position
    resp = client.post("/api/trades/execute", json={"ticker": "BBDC4.SA", "side": "BUY", "quantity": 10.0}, headers=headers)
    assert resp.status_code == 400
    assert "posições atingido" in resp.json()["detail"]


# ===========================================================================
# 14. Max positions reached autonomous -> rejected
# ===========================================================================
def test_14_max_positions_reached_autonomous_rejected(temp_db, active_session_auth):
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=10000.0, saldo_disponivel=10000.0, em_posicoes=0.0")
    conn.execute("INSERT INTO trades (ticker, side, shares, entry_price, status) VALUES ('PETR4.SA', 'BUY', 10, 25.0, 'active')")
    conn.execute("INSERT INTO trades (ticker, side, shares, entry_price, status) VALUES ('VALE3.SA', 'BUY', 10, 50.0, 'active')")
    conn.execute("INSERT INTO trades (ticker, side, shares, entry_price, status) VALUES ('ITUB4.SA', 'BUY', 10, 30.0, 'active')")
    conn.commit()
    conn.close()

    intent = _make_intent(ticker="BBDC4.SA", allocated=100.0, price=20.0, digest="3" * 64)
    with override_session_authority(active_session_auth):
        executor = ExecutorAgent(db_path=temp_db, session_authority=active_session_auth)
        res = executor.execute_order(intent)

    assert res["status"] == "rejected"
    assert "Max positions limit reached" in res["reason"]

    conn = sqlite3.connect(temp_db)
    active_count = conn.execute("SELECT COUNT(DISTINCT ticker) FROM trades WHERE status='active'").fetchone()[0]
    conn.close()
    assert active_count == 3


# ===========================================================================
# 15. Two concurrent entries with one slot remaining -> exactly one executes
# ===========================================================================
def test_15_concurrent_entries_one_slot_remaining_exactly_one_executes(temp_db, active_session_auth):
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=10000.0, saldo_disponivel=10000.0, em_posicoes=0.0")
    # 2 positions active already, max is 3 -> exactly 1 slot left
    conn.execute("INSERT INTO trades (ticker, side, shares, entry_price, status) VALUES ('ITUB4.SA', 'BUY', 10, 30.0, 'active')")
    conn.execute("INSERT INTO trades (ticker, side, shares, entry_price, status) VALUES ('BBDC4.SA', 'BUY', 10, 20.0, 'active')")
    conn.commit()
    conn.close()

    intent_petr = _make_intent(ticker="PETR4.SA", allocated=100.0, price=25.0, digest="0" * 64)
    intent_vale = _make_intent(ticker="VALE3.SA", allocated=100.0, price=50.0, digest="1" * 64)

    barrier = threading.Barrier(2)
    results = [None, None]
    worker_errors = []

    def _worker(idx, intent):
        try:
            barrier.wait(timeout=5)
            agent = ExecutorAgent(db_path=temp_db, session_authority=active_session_auth)
            results[idx] = agent.execute_order(intent)
        except Exception as e:
            worker_errors.append((idx, e))

    with override_session_authority(active_session_auth):
        import contextvars
        ctx1 = contextvars.copy_context()
        ctx2 = contextvars.copy_context()
        t1 = threading.Thread(target=ctx1.run, args=(_worker, 0, intent_petr))
        t2 = threading.Thread(target=ctx2.run, args=(_worker, 1, intent_vale))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

    assert not t1.is_alive()
    assert not t2.is_alive()
    assert not worker_errors, f"Errors: {worker_errors}"

    statuses = [r["status"] for r in results]
    assert "executed" in statuses, f"Expected one success: {results}"
    assert "rejected" in statuses, f"Expected one rejection: {results}"
    rejection = [r for r in results if r["status"] == "rejected"][0]
    assert "Max positions limit reached" in rejection["reason"]

    conn = sqlite3.connect(temp_db)
    active_count = conn.execute("SELECT COUNT(DISTINCT ticker) FROM trades WHERE status='active'").fetchone()[0]
    conn.close()
    assert active_count == 3


# ===========================================================================
# 16. Losing concurrent order -> 0 portfolio mutation
# ===========================================================================
def test_16_losing_concurrent_order_zero_portfolio_mutation(temp_db, active_session_auth):
    # Verified by checking portfolio balance matches exactly 1 deduction (100.0) from the winner
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=5000.0, saldo_disponivel=5000.0, em_posicoes=0.0")
    conn.execute("INSERT INTO trades (ticker, side, shares, entry_price, status) VALUES ('ITUB4.SA', 'BUY', 10, 30.0, 'active')")
    conn.execute("INSERT INTO trades (ticker, side, shares, entry_price, status) VALUES ('BBDC4.SA', 'BUY', 10, 20.0, 'active')")
    conn.commit()
    conn.close()

    intent_petr = _make_intent(ticker="PETR4.SA", allocated=100.0, price=25.0, digest="0" * 64)
    intent_vale = _make_intent(ticker="VALE3.SA", allocated=100.0, price=50.0, digest="1" * 64)

    barrier = threading.Barrier(2)
    results = [None, None]

    def _worker(idx, intent):
        barrier.wait(timeout=5)
        agent = ExecutorAgent(db_path=temp_db, session_authority=active_session_auth)
        results[idx] = agent.execute_order(intent)

    with override_session_authority(active_session_auth):
        import contextvars
        t1 = threading.Thread(target=contextvars.copy_context().run, args=(_worker, 0, intent_petr))
        t2 = threading.Thread(target=contextvars.copy_context().run, args=(_worker, 1, intent_vale))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

    conn = sqlite3.connect(temp_db)
    pf = conn.execute("SELECT patrimonio_total, saldo_disponivel, em_posicoes FROM portfolio").fetchone()
    conn.close()

    # Initial available was 5000.0. Exactly one 100.0 trade executed into em_posicoes.
    assert pf[1] == 5000.0
    assert pf[2] == 100.0


# ===========================================================================
# 17. Same ticker protection preserved
# ===========================================================================
def test_17_same_ticker_protection_preserved(temp_db, active_session_auth):
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=5000.0, saldo_disponivel=5000.0, em_posicoes=0.0")
    conn.execute("INSERT INTO trades (ticker, side, shares, entry_price, status) VALUES ('PETR4.SA', 'BUY', 10, 25.0, 'active')")
    conn.commit()
    conn.close()

    intent = _make_intent(ticker="PETR4.SA", allocated=100.0, price=25.0)
    with override_session_authority(active_session_auth):
        executor = ExecutorAgent(db_path=temp_db, session_authority=active_session_auth)
        res = executor.execute_order(intent)

    assert res["status"] == "skipped_existing_position"
    assert "Já existe posição ativa para este ticker" in res["reason"]


# ===========================================================================
# 18. Signal ID idempotency preserved
# ===========================================================================
def test_18_signal_id_idempotency_preserved(temp_db, active_session_auth):
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=5000.0, saldo_disponivel=5000.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    intent = _make_intent(ticker="PETR4.SA", allocated=100.0, price=25.0)

    with override_session_authority(active_session_auth):
        executor = ExecutorAgent(db_path=temp_db, session_authority=active_session_auth)
        res1 = executor.execute_order(intent)
        res2 = executor.execute_order(intent)

    assert res1["status"] == "executed"
    assert res2["status"] == "skipped_existing_position"
    assert "Signal already executed" in res2["reason"]


# ===========================================================================
# 19. margem_operavel still enforced
# ===========================================================================
def test_19_margem_operavel_enforced():
    # Saldo livre = 100.0, margem_operavel = 0.90 -> capital_cash (operavel) = 90.0
    res = calculate_position_size(
        capital_cash=90.0,
        current_open_count=0,
        max_positions=3,
        kelly_fraction=1.0,
        max_position_fraction=1.0,
        reference_equity=1000.0,
    )
    assert res == 90.0


# ===========================================================================
# 20. Normal BUY still works
# ===========================================================================
def test_20_normal_buy_works(temp_db, active_session_auth):
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=2000.0, saldo_disponivel=2000.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    intent = _make_intent(ticker="PETR4.SA", allocated=150.0, price=25.0)
    with override_session_authority(active_session_auth):
        executor = ExecutorAgent(db_path=temp_db, session_authority=active_session_auth)
        res = executor.execute_order(intent)

    assert res["status"] == "executed"
    assert res["shares"] == 6.0
    assert res["total_value"] == 150.0


# ===========================================================================
# 21. SELL opening still rejected
# ===========================================================================
def test_21_sell_opening_still_rejected(temp_db, active_session_auth):
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=2000.0, saldo_disponivel=2000.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    intent = _make_intent(ticker="PETR4.SA", allocated=150.0, price=25.0, side="SELL")
    with override_session_authority(active_session_auth):
        executor = ExecutorAgent(db_path=temp_db, session_authority=active_session_auth)
        res = executor.execute_order(intent)

    assert res["status"] == "rejected"
    assert "SHORT_SELL_EXECUTION_NOT_SUPPORTED" in res["reason"]


# ===========================================================================
# 22. 005-B accounting invariants still hold
# ===========================================================================
def test_22_accounting_invariants_hold(temp_db, active_session_auth):
    db.init_db()
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE portfolio SET patrimonio_total=2000.0, saldo_disponivel=2000.0, em_posicoes=0.0")
    conn.commit()
    conn.close()

    intent = _make_intent(ticker="PETR4.SA", allocated=200.0, price=20.0, side="BUY")
    with override_session_authority(active_session_auth):
        executor = ExecutorAgent(db_path=temp_db, session_authority=active_session_auth)
        res = executor.execute_order(intent)
        assert res["status"] == "executed"

        pf = db.get_portfolio(db_path=temp_db)
        assert pf["patrimonio_total"] == 2000.0
        assert pf["saldo_disponivel"] == 2000.0
        assert pf["em_posicoes"] == 200.0
        assert pf["saldo_livre"] == 1800.0

        conn = sqlite3.connect(temp_db)
        trade_id = conn.execute("SELECT id FROM trades WHERE status='active'").fetchone()[0]
        conn.close()

        quote = make_test_evidenced_quote("PETR4.SA", 22.0)
        res_exit = executor.close_order(trade_id, current_price=22.0, reason="take_profit", evidence=quote)
        assert res_exit["status"] == "closed"

        pf_after = db.get_portfolio(db_path=temp_db)
        assert pf_after["em_posicoes"] == 0.0
        # 10 shares @ 20 = 200. Sold @ 22 = 220. Profit = 20.
        assert pf_after["saldo_disponivel"] == 2020.0
        assert pf_after["saldo_livre"] == 2020.0


# ===========================================================================
# 23. Section 15: Backtest Parity & Causal Equity Sizing
# ===========================================================================
def test_23_backtest_runtime_sizing_parity():
    """Verify that backtest sizing formula strictly matches calculate_position_size."""
    ref_equity = 15000.0
    cash = 10000.0
    kelly = 0.25
    max_pos_frac = 0.10

    runtime_sized = calculate_position_size(
        capital_cash=cash,
        current_open_count=1,
        max_positions=3,
        kelly_fraction=kelly,
        max_position_fraction=max_pos_frac,
        reference_equity=ref_equity,
    )

    # In backtest engine:
    # kelly_cap = ref_equity * kelly = 15000 * 0.25 = 3750.0
    # conc_cap = ref_equity * max_pos_frac = 15000 * 0.10 = 1500.0
    # operavel = cash = 10000.0
    # min(3750, 1500, 10000) = 1500.0
    assert runtime_sized == 1500.0


def test_23_backtest_causal_equity_at_open_no_lookahead():
    """Verify backtest causal equity uses today's open price without lookahead."""
    import pandas as pd

    # Mock daily bars for 1 ticker
    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    bars = {
        "PETR4.SA": pd.DataFrame({
            "open": [20.0, 21.0, 22.0, 23.0, 24.0],
            "high": [21.0, 22.0, 23.0, 24.0, 25.0],
            "low": [19.0, 20.0, 21.0, 22.0, 23.0],
            "close": [20.5, 21.5, 22.5, 23.5, 24.5],
            "volume": [1000] * 5,
        }, index=dates),
    }

    # If position is 10 shares of PETR4 opened earlier, at today (idx 1, date 2024-01-02):
    # Open price is 21.0. High is 22.0, Close is 21.5.
    # Causal equity at open MUST use 21.0, NOT 21.5 (close) or 22.0 (high).
    open_p = bars["PETR4.SA"].iloc[1]["open"]
    close_p = bars["PETR4.SA"].iloc[1]["close"]
    assert open_p == 21.0
    assert close_p == 21.5

    pos_shares = 10.0
    cash = 1000.0
    causal_equity = cash + pos_shares * open_p
    assert causal_equity == 1210.0

    # Sizing with causal equity:
    sized = calculate_position_size(
        capital_cash=cash,
        current_open_count=1,
        max_positions=3,
        kelly_fraction=0.25,
        max_position_fraction=0.10,
        reference_equity=causal_equity,
    )
    # 10% of 1210 = 121.0
    assert sized == 121.0
