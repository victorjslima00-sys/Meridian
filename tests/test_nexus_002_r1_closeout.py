"""Adversarial Closeout Test Suite (NEXUS-002-R1).

Validates:
A. REAL AUTONOMOUS PATH: MarketAnalyst BUY -> TypedSignal -> RiskDecision -> ApprovedExecutionIntent -> Paper execution.
B. MISSING PROVENANCE: Legacy MarketAnalyst BUY lacking dataset identity rejected before mutation.
C. FORGED RAW APPROVAL: Plausible raw approved dict rejected with 0 new trades and unchanged portfolio.
D. MANUAL STRING BYPASS: reason="Manual" cannot enter manual path via execute_order.
E. FORGED INTENT: Arbitrary formatted IDs cannot execute.
F. SIGNAL/RISK MISMATCH: Valid signal A + valid decision bound to signal B rejected before transaction.
G. PAPERBROKER: Raw dictionaries rejected, typed ApprovedExecutionIntent accepted.
H. JOURNAL: SIGNAL_EVALUATED payload equals sanitized validated contract, not raw input.
"""
from datetime import datetime, timezone
import sqlite3
from unittest.mock import patch
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from backend.app.agents.contracts import (
    ApprovedExecutionIntent,
    ManualExecutionIntent,
    RiskDecision,
    TypedSignal,
)
from backend.app.agents.executor import ExecutorAgent
from backend.app.agents.market_analyst import MarketAnalyst
from backend.app.agents.risk_manager import RiskManager
from backend.app.markets.paper_broker import PaperBroker
from trading_bot.data.approval import (
    Approval,
    Evidence,
    compute_candidate_id,
    dataset_digest,
)
from trading_bot.execution.paper_session import PaperSessionRunner


def _daily_breakout_df(n: int = 250, breakout: float = 1.02) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    price = 85.0
    closes = []
    for _ in range(n - 1):
        price += 0.015 + rng.normal(0, 0.35)
        closes.append(price)
    recent_high = max(closes[-20:])
    closes.append(recent_high * breakout)
    highs = [c * 1.006 if i < n - 1 else c * 1.001 for i, c in enumerate(closes)]
    return pd.DataFrame({
        "date": pd.date_range("2023-01-02", periods=n, freq="D"),
        "close": closes,
        "open": [c * 0.999 for c in closes],
        "high": highs,
        "low": [c * 0.994 for c in closes],
        "volume": [1000] * (n - 1) + [2500],
    })


VALID_SHA256 = "a" * 64


@pytest.fixture
def synthetic_approval(monkeypatch):
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
        review_notes="synthetic closeout fixture",
        status="approved",
    )
    monkeypatch.setattr(
        "trading_bot.data.approval.require_dataset_approval_by_digest",
        lambda d, *a, **kw: appr if d == VALID_SHA256 else (_ for _ in ()).throw(ValueError("data_approval_required")),
    )
    return appr


@pytest.fixture
def isolated_db(tmp_path):
    db_file = tmp_path / "closeout_test.db"
    conn = sqlite3.connect(str(db_file))
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
            patrimonio_total REAL DEFAULT 1000.0,
            saldo_disponivel REAL DEFAULT 1000.0,
            em_posicoes REAL DEFAULT 0.0,
            margem_operavel REAL,
            updated_at TIMESTAMP
        )
    """)
    cursor.execute(
        "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, updated_at) "
        "VALUES (1000.0, 1000.0, 0.0, ?)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    cursor.execute(
        "CREATE UNIQUE INDEX idx_trades_strategy_signal_id ON trades(signal_id) WHERE signal_id IS NOT NULL"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX idx_trades_single_active ON trades(ticker) WHERE status = 'active'"
    )
    conn.commit()
    conn.close()
    return str(db_file)


def _get_db_state(db_path: str):
    conn = sqlite3.connect(db_path)
    trades_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    pf = conn.execute("SELECT saldo_disponivel, em_posicoes FROM portfolio ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return trades_count, pf


# ---------------------------------------------------------------------------
# Test A: True MarketAnalyst Autonomous Path Integration
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_real_market_analyst_autonomous_path_with_valid_approval(
    isolated_db, monkeypatch, mock_circuit_breaker
):
    """A. REAL AUTONOMOUS PATH: MarketAnalyst.analyze() -> TypedSignal -> RiskDecision -> ApprovedExecutionIntent -> Paper DB mutation."""
    ticker = "PETR4.SA"
    df = _daily_breakout_df(breakout=1.02)

    # Compute eng_df and real dataset_digest exactly as MarketAnalyst does
    eng_df = pd.DataFrame(
        {
            "ts": pd.to_datetime(df["date"]).dt.date,
            "adj_close": df["close"].astype(float),
            "o": df["open"].astype(float),
            "c": df["close"].astype(float),
            "h": df["high"].astype(float),
            "l": df["low"].astype(float),
            "v": df["volume"].astype(float),
        }
    )
    real_digest = dataset_digest(eng_df, ticker)

    # Register temporary approval for this exact real digest
    ev = Evidence(path="synthetic_evidence.csv", sha256=real_digest)
    c_id = compute_candidate_id(
        ticker=ticker,
        strategy_id="donchian_breakout",
        intended_use="PAPER_TRADING",
        dataset_sha256=real_digest,
        collected_at_utc="2026-09-16T12:00:00Z",
        dataset_artifact_sha256=ev.sha256,
        review_csv_sha256=ev.sha256,
        source_sha256=ev.sha256,
        calendar_sha256=ev.sha256,
        adjustments_sha256=ev.sha256,
        point_in_time_sha256=ev.sha256,
    )
    real_approval = Approval(
        candidate_id=c_id,
        ticker=ticker,
        strategy_id="donchian_breakout",
        intended_use="PAPER_TRADING",
        dataset_sha256=real_digest,
        collected_at_utc="2026-09-16T12:00:00Z",
        dataset_artifact=ev,
        review_csv=ev,
        source=ev,
        calendar=ev,
        adjustments=ev,
        point_in_time=ev,
        reviewed_by="nexus-002-r2-auditor",
        review_notes="temporary fixture for real market analyst integration",
        status="approved",
    )
    monkeypatch.setattr(
        "trading_bot.data.approval.require_dataset_approval_by_digest",
        lambda d, *a, **kw: real_approval if d == real_digest else (_ for _ in ()).throw(ValueError("data_approval_required")),
    )

    ibov_mock_df = pd.DataFrame({
        "ts": pd.date_range("2023-01-02", periods=260, freq="D").date,
        "c": [120000.0] * 260,
        "sma50": [115000.0] * 260,
    })

    # Execute actual MarketAnalyst.analyze()
    with patch("backend.app.data.feed.fetch_recent_data", return_value=df), \
         patch("backend.app.agents.market_analyst.get_ibov_data", return_value=ibov_mock_df):
        analyst = MarketAnalyst(ticker)
        analysis = await analyst.analyze()

    assert analysis["signal"] == "BUY"
    assert analysis["side"] == "BUY"
    assert analysis["dataset_sha256"] == real_digest
    assert analysis["dataset_approved"] is True
    assert analysis["strategy_id"] == "donchian_breakout"
    assert analysis["generated_at"].tzinfo is not None

    # 1. TypedSignal validation
    sig = TypedSignal.model_validate(analysis)
    assert sig.signal_id.startswith("sig_")
    assert sig.dataset_sha256 == real_digest

    # 2. RiskManager evaluation
    rm = RiskManager(saldo_livre=1000.0, em_posicoes=0.0)
    decision = rm.evaluate_trade(sig, ticker=ticker)
    assert isinstance(decision, RiskDecision)
    assert decision.approved is True
    assert decision.signal_id == sig.signal_id

    # 3. ApprovedExecutionIntent construction
    intent = ApprovedExecutionIntent(signal=sig, risk_decision=decision)
    assert intent.intent_id.startswith("exec_")
    assert intent.signal_id == sig.signal_id
    assert intent.decision_id == decision.decision_id

    # 4. ExecutorAgent execution
    executor = ExecutorAgent(db_path=isolated_db)
    res = executor.execute_order(intent)
    assert res["status"] == "executed"
    assert res["ticker"] == ticker
    assert res["shares"] > 0

    # 5. Database verification
    trades_count, pf = _get_db_state(isolated_db)
    assert trades_count == 1
    assert pf[1] > 0


@pytest.mark.asyncio
async def test_a2_real_market_analyst_unapproved_dataset_results_in_hold_and_no_mutation(
    isolated_db, monkeypatch
):
    """Prove the same market dataset WITHOUT its approval results in HOLD / no execution authority / zero DB mutation."""
    ticker = "PETR4.SA"
    df = _daily_breakout_df(breakout=1.02)
    trades_before, pf_before = _get_db_state(isolated_db)

    # Disallow approval (fail closed)
    monkeypatch.setattr(
        "trading_bot.data.approval.require_dataset_approval_by_digest",
        lambda d: (_ for _ in ()).throw(ValueError("data_approval_required")),
    )

    with patch("backend.app.data.feed.fetch_recent_data", return_value=df), \
         patch("backend.app.agents.market_analyst.get_ibov_data", return_value=None):
        analyst = MarketAnalyst(ticker)
        unapproved_analysis = await analyst.analyze()

    assert unapproved_analysis["signal"] == "HOLD"
    assert unapproved_analysis["side"] == "HOLD"
    assert unapproved_analysis["dataset_approved"] is False
    assert unapproved_analysis["dataset_sha256"] is None

    # TypedSignal for HOLD
    hold_sig = TypedSignal.model_validate(unapproved_analysis)
    assert hold_sig.side == "HOLD"

    # RiskManager rejects HOLD
    rm = RiskManager(saldo_livre=1000.0)
    hold_decision = rm.evaluate_trade(hold_sig, ticker=ticker)
    assert hold_decision.approved is False
    assert "HOLD" in hold_decision.reason

    # ApprovedExecutionIntent cannot be formed for HOLD (rejected risk decision)
    with pytest.raises((ValidationError, ValueError)):
        ApprovedExecutionIntent(signal=hold_sig, risk_decision=hold_decision)

    # Even with forged approved=True decision, HOLD is rejected by signal.side invariant
    forged_approved_dec = RiskDecision(
        signal_id=hold_sig.signal_id,
        approved=True,
        allocated_capital=100.0,
        target_price=33.0,
        stop_loss=28.5,
        reason="Forged",
        decision_timestamp=datetime.now(timezone.utc),
    )
    with pytest.raises((ValidationError, ValueError), match="must be BUY or SELL"):
        ApprovedExecutionIntent(signal=hold_sig, risk_decision=forged_approved_dec)

    # Zero DB mutation
    trades_after, pf_after = _get_db_state(isolated_db)
    assert trades_after == trades_before == 0
    assert pf_after == pf_before


# ---------------------------------------------------------------------------
# Test B: Missing Provenance
# ---------------------------------------------------------------------------
def test_b_missing_provenance_rejected_before_mutation(isolated_db):
    """B. MISSING PROVENANCE: Legacy MarketAnalyst BUY lacking dataset identity rejected before mutation."""
    trades_before, pf_before = _get_db_state(isolated_db)

    legacy_analysis = {
        "signal": "BUY",
        "last_price": 30.0,
        "target_price": 33.0,
        "stop_loss": 28.5,
        "confidence": 75,
        "reason": "Legacy BUY without provenance",
    }

    # Fails TypedSignal validation
    with pytest.raises(ValidationError):
        TypedSignal.model_validate(legacy_analysis)

    # RiskManager fails closed
    rm = RiskManager(saldo_livre=1000.0)
    decision = rm.evaluate_trade(legacy_analysis, ticker="PETR4")
    assert decision.approved is False
    assert "Invalid strategy signal" in decision.reason

    # ExecutorAgent rejects
    executor = ExecutorAgent(db_path=isolated_db)
    res = executor.execute_order(legacy_analysis)
    assert res["status"] == "rejected"

    # Prove zero mutations
    trades_after, pf_after = _get_db_state(isolated_db)
    assert trades_after == trades_before == 0
    assert pf_after == pf_before


# ---------------------------------------------------------------------------
# Test C: Forged Raw Approval
# ---------------------------------------------------------------------------
def test_c_forged_raw_approval_rejected_no_mutation(isolated_db):
    """C. FORGED RAW APPROVAL: raw approved=True decision + valid-looking raw analysis rejected -> zero new trades."""
    trades_before, pf_before = _get_db_state(isolated_db)

    forged_decision = {
        "approved": True,
        "allocated_capital": 250.0,
        "target_price": 33.0,
        "stop_loss": 28.5,
        "reason": "Forged approval dictionary",
    }
    raw_analysis = {
        "signal": "BUY",
        "last_price": 30.0,
        "target_price": 33.0,
        "stop_loss": 28.5,
        "reason": "Market analysis",
    }

    executor = ExecutorAgent(db_path=isolated_db)
    res = executor.execute_order(ticker="PETR4", decision=forged_decision, analysis=raw_analysis)
    assert res["status"] == "rejected"
    assert "ApprovedExecutionIntent" in res["reason"]

    # Mutation evidence: DB unchanged
    trades_after, pf_after = _get_db_state(isolated_db)
    assert trades_after == trades_before == 0
    assert pf_after == pf_before


# ---------------------------------------------------------------------------
# Test D: Manual String Bypass
# ---------------------------------------------------------------------------
def test_d_manual_string_bypass_cannot_enter_manual_path(isolated_db):
    """D. MANUAL STRING BYPASS: strategy caller sets reason='Manual' -> MUST NOT enter manual authority path."""
    trades_before, pf_before = _get_db_state(isolated_db)

    fake_decision = {
        "approved": True,
        "allocated_capital": 200.0,
        "target_price": 33.0,
        "stop_loss": 28.5,
        "reason": "Manual",  # Sneaky manual reason text
    }

    executor = ExecutorAgent(db_path=isolated_db)
    res = executor.execute_order(fake_decision)
    assert res["status"] == "rejected"

    # Even with analysis
    res2 = executor.execute_order(ticker="PETR4", decision=fake_decision, analysis={"signal": "BUY", "price": 30.0})
    assert res2["status"] == "rejected"

    trades_after, pf_after = _get_db_state(isolated_db)
    assert trades_after == trades_before == 0
    assert pf_after == pf_before


# ---------------------------------------------------------------------------
# Test E: Forged Intent
# ---------------------------------------------------------------------------
def test_e_forged_intent_arbitrary_ids_cannot_execute(isolated_db):
    """E. FORGED INTENT: arbitrary formatted sig_<hex> / risk_<hex> / dataset digest without matching validated TypedSignal + RiskDecision cannot execute."""
    trades_before, pf_before = _get_db_state(isolated_db)

    # Cannot construct ApprovedExecutionIntent with free-standing arbitrary IDs
    with pytest.raises(Exception):
        ApprovedExecutionIntent(
            signal_id="sig_" + "b" * 64,
            decision_id="risk_" + "c" * 64,
            ticker="PETR4",
            side="BUY",
            entry_price=30.0,
            allocated_capital=100.0,
            target_price=33.0,
            stop_loss=28.5,
            dataset_sha256="d" * 64,
        )

    # Passing raw dict with arbitrary IDs to executor is rejected
    executor = ExecutorAgent(db_path=isolated_db)
    res = executor.execute_order({
        "signal_id": "sig_" + "b" * 64,
        "decision_id": "risk_" + "c" * 64,
        "ticker": "PETR4",
        "side": "BUY",
        "entry_price": 30.0,
    })
    assert res["status"] == "rejected"

    trades_after, pf_after = _get_db_state(isolated_db)
    assert trades_after == 0
    assert pf_after == pf_before


# ---------------------------------------------------------------------------
# Test F: Signal/Risk Mismatch
# ---------------------------------------------------------------------------
def test_f_signal_risk_mismatch_rejected_before_transaction(isolated_db, synthetic_approval):
    """F. SIGNAL/RISK MISMATCH: valid signal A + valid decision bound to signal B -> reject before transaction."""
    trades_before, pf_before = _get_db_state(isolated_db)

    now = datetime.now(timezone.utc)
    sig_a = TypedSignal(
        ticker="PETR4",
        side="BUY",
        price=30.0,
        target_price=33.0,
        stop_loss=28.5,
        reason="Signal A",
        dataset_sha256=VALID_SHA256,
        dataset_approved=True,
        generated_at=now,
    )

    sig_b = TypedSignal(
        ticker="VALE3",
        side="BUY",
        price=60.0,
        target_price=66.0,
        stop_loss=57.0,
        reason="Signal B",
        dataset_sha256=VALID_SHA256,
        dataset_approved=True,
        generated_at=now,
    )
    dec_b = RiskDecision(
        signal_id=sig_b.signal_id,
        approved=True,
        allocated_capital=100.0,
        target_price=66.0,
        stop_loss=57.0,
        reason="Decision for B",
        decision_timestamp=now,
    )

    # Combining Signal A with Decision for Signal B must be rejected by validator
    with pytest.raises(ValueError, match="does not match"):
        ApprovedExecutionIntent(signal=sig_a, risk_decision=dec_b)

    trades_after, pf_after = _get_db_state(isolated_db)
    assert trades_after == 0
    assert pf_after == pf_before


# ---------------------------------------------------------------------------
# Test G: PaperBroker Typed Boundary
# ---------------------------------------------------------------------------
def test_g_paperbroker_rejects_raw_dicts_accepts_typed_intent(isolated_db, synthetic_approval):
    """G. PAPERBROKER: raw dictionaries rejected/not accepted by API; Typed ApprovedExecutionIntent accepted."""
    broker = PaperBroker()

    # 1. Raw dicts rejected
    res_raw1 = broker.execute_order({"approved": True})
    assert res_raw1["status"] == "rejected"

    res_raw2 = broker.execute_order("PETR4", {"approved": True}, {"signal": "BUY"})
    assert res_raw2["status"] == "rejected"

    # 2. Typed intent accepted
    sig = TypedSignal(
        ticker="PETR4",
        side="BUY",
        price=30.0,
        target_price=33.0,
        stop_loss=28.5,
        reason="Valid signal",
        dataset_sha256=VALID_SHA256,
        dataset_approved=True,
        generated_at=datetime.now(timezone.utc),
    )
    dec = RiskDecision(
        signal_id=sig.signal_id,
        approved=True,
        allocated_capital=150.0,
        target_price=33.0,
        stop_loss=28.5,
        reason="Approved",
        decision_timestamp=datetime.now(timezone.utc),
    )
    intent = ApprovedExecutionIntent(signal=sig, risk_decision=dec)

    # Use isolated_db for executor agent
    from unittest.mock import patch
    with patch.object(broker, "_agent", return_value=ExecutorAgent(db_path=isolated_db)):
        res_typed = broker.execute_order(intent)
        assert res_typed["status"] == "executed"


# ---------------------------------------------------------------------------
# Test H: Paper Session Journal Sanitization
# ---------------------------------------------------------------------------
def test_h_journal_sanitized_validated_signal(tmp_path, synthetic_approval, mock_circuit_breaker):
    """H. JOURNAL: SIGNAL_EVALUATED payload equals validated/sanitized signal contract, not original raw input."""
    db_file = tmp_path / "paper_journal.db"
    storage_dir = tmp_path / "sessions"

    # Create isolated db
    conn = sqlite3.connect(str(db_file))
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, side TEXT, shares REAL, entry_price REAL,
            exit_price REAL, target_price REAL, stop_loss REAL,
            entry_date TIMESTAMP, exit_date TIMESTAMP, pnl_pct REAL,
            exit_reason TEXT, ai_rationale TEXT, status TEXT, signal_id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patrimonio_total REAL, saldo_disponivel REAL, em_posicoes REAL, margem_operavel REAL, updated_at TIMESTAMP
        )
    """)
    conn.execute("INSERT INTO portfolio VALUES (1, 1000.0, 1000.0, 0.0, 1000.0, ?)", (datetime.now(timezone.utc).isoformat(),))
    conn.execute("CREATE UNIQUE INDEX idx_trades_signal_id ON trades(signal_id) WHERE signal_id IS NOT NULL")
    conn.execute("CREATE UNIQUE INDEX idx_trades_active ON trades(ticker) WHERE status = 'active'")
    conn.commit()
    conn.close()

    now = datetime.now(timezone.utc)
    raw_signal = {
        "ticker": "PETR4",
        "signal": "BUY",  # Alias that gets normalized to 'side'
        "current_price": 30.0,  # Alias that gets normalized to 'price'
        "target_price": 33.0,
        "stop_loss": 28.5,
        "confidence": 75,
        "reason": "Test breakout",
        "generated_at": now.isoformat(),
        "dataset_sha256": VALID_SHA256,
        "dataset_approved": True,
    }

    runner = PaperSessionRunner(session_id="session_h", db_path=str(db_file), storage_dir=str(storage_dir))
    report = runner.run_cycle(signals=[raw_signal])
    assert report.orders_executed == 1

    # Inspect journal events
    eval_events = [e for e in runner.journal.events if e.event_type == "SIGNAL_EVALUATED"]
    assert len(eval_events) == 1
    eval_payload = eval_events[0].payload

    # Validated payload has normalized fields
    assert eval_payload["side"] == "BUY"
    assert eval_payload["price"] == 30.0
    assert eval_payload["signal_id"].startswith("sig_")
    # Must NOT have unnormalized aliases from raw input
    assert "current_price" not in eval_payload


# ---------------------------------------------------------------------------
# Section 1: Authority Immutability & Post-Validation Mutation Tests
# ---------------------------------------------------------------------------
def test_mutation_a_signal_tampering_rejected_no_db_mutation(
    isolated_db, synthetic_approval, mock_circuit_breaker
):
    """A. Create valid TypedSignal; mutate price/ticker/dataset/target after validation; attempt execution; REJECT, zero DB/portfolio mutation."""
    trades_before, pf_before = _get_db_state(isolated_db)
    now = datetime.now(timezone.utc)
    sig = TypedSignal(
        ticker="PETR4",
        side="BUY",
        price=30.0,
        target_price=33.0,
        stop_loss=28.5,
        reason="Breakout",
        dataset_sha256=VALID_SHA256,
        dataset_approved=True,
        generated_at=now,
    )
    dec = RiskDecision(
        signal_id=sig.signal_id,
        approved=True,
        reason="Approved",
        allocated_capital=100.0,
        target_price=33.0,
        stop_loss=28.5,
        decision_timestamp=now,
    )
    intent = ApprovedExecutionIntent(signal=sig, risk_decision=dec)

    # Post-validation mutation of price
    intent.signal.price = 31.0

    executor = ExecutorAgent(db_path=isolated_db)
    res = executor.execute_order(intent)
    assert res["status"] == "rejected"
    assert "Authority graph revalidation failed" in res["reason"]

    # Verify zero DB mutation
    trades_after, pf_after = _get_db_state(isolated_db)
    assert trades_after == trades_before == 0
    assert pf_after == pf_before


def test_mutation_b_allocated_capital_tampering_rejected(
    isolated_db, synthetic_approval, mock_circuit_breaker
):
    """B. Create valid RiskDecision; mutate allocated_capital after decision_id creation; attempt execution; REJECT."""
    trades_before, pf_before = _get_db_state(isolated_db)
    now = datetime.now(timezone.utc)
    sig = TypedSignal(
        ticker="PETR4",
        side="BUY",
        price=30.0,
        target_price=33.0,
        stop_loss=28.5,
        reason="Breakout",
        dataset_sha256=VALID_SHA256,
        dataset_approved=True,
        generated_at=now,
    )
    dec = RiskDecision(
        signal_id=sig.signal_id,
        approved=True,
        reason="Approved",
        allocated_capital=100.0,
        target_price=33.0,
        stop_loss=28.5,
        decision_timestamp=now,
    )
    intent = ApprovedExecutionIntent(signal=sig, risk_decision=dec)

    # Post-validation mutation of allocated_capital on decision
    intent.risk_decision.allocated_capital = 5000.0

    executor = ExecutorAgent(db_path=isolated_db)
    res = executor.execute_order(intent)
    assert res["status"] == "rejected"
    assert "Authority graph revalidation failed" in res["reason"]

    trades_after, pf_after = _get_db_state(isolated_db)
    assert trades_after == 0
    assert pf_after == pf_before


def test_mutation_c_target_stop_tampering_rejected(
    isolated_db, synthetic_approval, mock_circuit_breaker
):
    """C. Mutate target/stop after decision validation; REJECT."""
    trades_before, pf_before = _get_db_state(isolated_db)
    now = datetime.now(timezone.utc)
    sig = TypedSignal(
        ticker="PETR4",
        side="BUY",
        price=30.0,
        target_price=33.0,
        stop_loss=28.5,
        reason="Breakout",
        dataset_sha256=VALID_SHA256,
        dataset_approved=True,
        generated_at=now,
    )
    dec = RiskDecision(
        signal_id=sig.signal_id,
        approved=True,
        reason="Approved",
        allocated_capital=100.0,
        target_price=33.0,
        stop_loss=28.5,
        decision_timestamp=now,
    )
    intent = ApprovedExecutionIntent(signal=sig, risk_decision=dec)

    # Post-validation mutation of target price
    intent.risk_decision.target_price = 45.0

    executor = ExecutorAgent(db_path=isolated_db)
    res = executor.execute_order(intent)
    assert res["status"] == "rejected"
    assert "Authority graph revalidation failed" in res["reason"]

    trades_after, pf_after = _get_db_state(isolated_db)
    assert trades_after == 0
    assert pf_after == pf_before


def test_mutation_d_manual_intent_tampering_rejected(isolated_db):
    """D. Mutate ManualExecutionIntent after construction into invalid financial state; REJECT before DB mutation."""
    trades_before, pf_before = _get_db_state(isolated_db)
    manual = ManualExecutionIntent(
        ticker="PETR4",
        side="BUY",
        entry_price=30.0,
        allocated_capital=100.0,
        target_price=33.0,
        stop_loss=28.5,
        reason="Manual order",
        operator="trader_1",
    )

    # Mutate allocated_capital into invalid state
    manual.allocated_capital = -10.0

    executor = ExecutorAgent(db_path=isolated_db)
    res = executor.execute_manual_order(manual)
    assert res["status"] == "rejected"
    assert "Manual authority revalidation failed" in res["reason"]

    trades_after, pf_after = _get_db_state(isolated_db)
    assert trades_after == 0
    assert pf_after == pf_before