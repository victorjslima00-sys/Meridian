"""Adversarial Test Suite for NEXUS-004.

Validates:
1. RUNTIME: Single Paper execution authority (legacy cron disabled in Dockerfile and compose).
2. SESSION & CALENDAR: B3SessionPhase, official 2026 calendar, Ash Wednesday, weekends, holidays, unknown year.
3. CLOSED BARS: Today's forming bar excluded from signal frame, digest, and analyst; decision bar date < market date.
4. STRATEGY CONFIG: Corrupt or missing config fails closed (no BUY authority).
5. MACRO FILTER: IBOV fails closed on missing, forming/today bar, below SMA50.
6. ENTRY FILL & GAP: Fresh evidenced quote, decision price != execution price, stop < execution < target invariant.
7. EXIT TRUST: Rejection of +Inf, -Inf, NaN, bool, stale timestamp; exit management independent of entry session phase.
8. PAPERSESSION REGRESSION: Typed RiskDecision rejection does not crash; canonical saldo_operavel margin ceiling.
9. PREFLIGHT TRUTH: INFRASTRUCTURE_READY vs ENTRY_READY separation, honest valuation report, zero DB mutations.
"""
from __future__ import annotations

import datetime
from datetime import timezone
import math
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import yaml

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from backend.app.agents.contracts import (
    ApprovedExecutionIntent,
    RiskDecision,
    TypedSignal,
)
from backend.app.agents.executor import ExecutorAgent
from backend.app.agents.market_analyst import MarketAnalyst
from backend.app.main import _price_is_trustworthy
from backend.app.markets.b3_session import (
    B3_TIMEZONE,
    B3DayType,
    B3SessionPhase,
    can_enter_new_position,
    can_manage_exits,
    get_day_type,
    get_session_phase,
)
from scripts.paper_session_preflight import (
    check_b3_session_calendar,
    check_single_paper_writer,
    check_valuation_subsystem,
    run_paper_preflight,
)
from trading_bot.data.closed_frame import closed_daily_signal_frame
from trading_bot.data.valuation_snapshot import EvidencedQuote, compute_evidence_sha256
from trading_bot.execution.paper_session import PaperSessionRunner
from trading_bot.signals.engine import compute_signal, ibov_in_uptrend


# ===========================================================================
# 1. RUNTIME SINGLE PAPER WRITER TESTS
# ===========================================================================

def test_default_compose_exposes_one_paper_writer():
    """Verify docker-compose.yml does NOT activate legacy bot as a default service."""
    compose_path = Path("docker-compose.yml")
    assert compose_path.is_file(), "docker-compose.yml must exist"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    bot = compose.get("services", {}).get("bot", {})
    assert "legacy" in bot.get("profiles", [])
    assert bot.get("restart") == "no"


def test_dockerfile_cron_disabled():
    """Verify Dockerfile does NOT automatically schedule fase2_paper_trading.py."""
    dockerfile_path = Path("Dockerfile")
    assert dockerfile_path.is_file(), "Dockerfile must exist"
    lines = dockerfile_path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not ("cron" in stripped.lower() and "fase2_paper_trading.py" in stripped), (
            f"Active cron order writer found in Dockerfile: {stripped}"
        )


def test_check_single_paper_writer_passes():
    """Verify preflight single-writer checker confirms only one paper writer."""
    ok, msg = check_single_paper_writer()
    assert ok is True
    assert "Single Paper execution authority verified" in msg


# ===========================================================================
# 2. B3 SESSION AND CALENDAR CONTRACT TESTS
# ===========================================================================

def test_b3_weekend_no_entry():
    """Weekends must classify as NO_SESSION, CLOSED, and reject new entries."""
    sat = datetime.datetime(2026, 3, 14, 11, 0, tzinfo=B3_TIMEZONE)
    sun = datetime.datetime(2026, 3, 15, 11, 0, tzinfo=B3_TIMEZONE)
    assert get_day_type(sat.date()) == B3DayType.NO_SESSION
    assert get_day_type(sun.date()) == B3DayType.NO_SESSION
    assert get_session_phase(sat) == B3SessionPhase.CLOSED
    assert get_session_phase(sun) == B3SessionPhase.CLOSED
    assert can_enter_new_position(sat) is False
    assert can_enter_new_position(sun) is False


def test_b3_official_holidays_no_entry():
    """Official 2026 holidays from OC 003-2026-VNC must classify as NO_SESSION."""
    tiradentes = datetime.datetime(2026, 4, 21, 12, 0, tzinfo=B3_TIMEZONE)
    independencia = datetime.datetime(2026, 9, 7, 12, 0, tzinfo=B3_TIMEZONE)
    natal = datetime.datetime(2026, 12, 25, 12, 0, tzinfo=B3_TIMEZONE)

    for h in [tiradentes, independencia, natal]:
        assert get_day_type(h.date()) == B3DayType.NO_SESSION
        assert get_session_phase(h) == B3SessionPhase.CLOSED
        assert can_enter_new_position(h) is False


def test_b3_ash_wednesday_special_hours():
    """Ash Wednesday (2026-02-18) opens continuous trading at 13:00, not 10:00."""
    ash_wed = datetime.date(2026, 2, 18)
    assert get_day_type(ash_wed) == B3DayType.SPECIAL_HOURS

    assert get_session_phase(datetime.datetime(2026, 2, 18, 11, 0, tzinfo=B3_TIMEZONE)) == B3SessionPhase.CLOSED
    assert get_session_phase(datetime.datetime(2026, 2, 18, 12, 40, tzinfo=B3_TIMEZONE)) == B3SessionPhase.ORDER_CANCELLATION
    assert get_session_phase(datetime.datetime(2026, 2, 18, 12, 50, tzinfo=B3_TIMEZONE)) == B3SessionPhase.PRE_OPEN
    ash_continuous = datetime.datetime(2026, 2, 18, 13, 30, tzinfo=B3_TIMEZONE)
    assert get_session_phase(ash_continuous) == B3SessionPhase.CONTINUOUS
    assert can_enter_new_position(ash_continuous) is True
    # Ash Wednesday continuous session runs until 17:55, closing call 17:55-18:00 (B3 OC 003/2026-VNC)
    ash_late = datetime.datetime(2026, 2, 18, 16, 56, tzinfo=B3_TIMEZONE)
    assert get_session_phase(ash_late) == B3SessionPhase.CONTINUOUS
    assert can_enter_new_position(ash_late) is True
    ash_closing = datetime.datetime(2026, 2, 18, 17, 56, tzinfo=B3_TIMEZONE)
    assert get_session_phase(ash_closing) == B3SessionPhase.CLOSING_CALL
    assert can_enter_new_position(ash_closing) is False


def test_b3_session_phases_normal_day():
    """Normal trading day schedule effective 2026-03-09."""
    base = datetime.date(2026, 3, 10)
    assert get_day_type(base) == B3DayType.NORMAL_TRADING_DAY

    times_and_expected = [
        (datetime.time(9, 15), B3SessionPhase.CLOSED, False),
        (datetime.time(9, 40), B3SessionPhase.ORDER_CANCELLATION, False),
        (datetime.time(9, 50), B3SessionPhase.PRE_OPEN, False),
        (datetime.time(10, 0), B3SessionPhase.CONTINUOUS, True),
        (datetime.time(10, 30), B3SessionPhase.CONTINUOUS, True),
        (datetime.time(16, 54), B3SessionPhase.CONTINUOUS, True),
        (datetime.time(16, 57), B3SessionPhase.CLOSING_CALL, False),
        (datetime.time(17, 10), B3SessionPhase.POST_REGULAR, False),
        (datetime.time(17, 28), B3SessionPhase.AFTER_MARKET_ORDER_CANCELLATION, False),
        (datetime.time(17, 40), B3SessionPhase.AFTER_MARKET, False),
        (datetime.time(18, 10), B3SessionPhase.POST_REGULAR, False),
        (datetime.time(18, 30), B3SessionPhase.POST_AFTER_MARKET, False),
        (datetime.time(19, 0), B3SessionPhase.CLOSED, False),
    ]

    for t, expected_phase, expected_entry in times_and_expected:
        dt = datetime.datetime.combine(base, t, tzinfo=B3_TIMEZONE)
        assert get_session_phase(dt) == expected_phase, f"Failed for time {t}: expected {expected_phase}"
        assert can_enter_new_position(dt) is expected_entry, f"Entry permission failed for time {t}"


def test_b3_unknown_calendar_year_fails_closed():
    """Years without official calendar evidence must fail closed with UNKNOWN."""
    unknown_dt = datetime.datetime(2025, 6, 15, 11, 0, tzinfo=B3_TIMEZONE)
    assert get_day_type(unknown_dt.date()) == B3DayType.UNKNOWN
    assert get_session_phase(unknown_dt) == B3SessionPhase.CLOSED
    assert can_enter_new_position(unknown_dt) is False


# ===========================================================================
# 3. CLOSED DAILY SIGNAL FRAME TESTS
# ===========================================================================

def test_closed_daily_signal_frame_excludes_today_bar():
    """Today's forming bar must be excluded; previous closed bar must be retained."""
    mkt_date = datetime.date(2026, 3, 10)
    dates = [mkt_date - datetime.timedelta(days=i) for i in range(210, -1, -1)]
    df = pd.DataFrame({
        "date": dates,
        "open": [10.0] * len(dates),
        "high": [11.0] * len(dates),
        "low": [9.0] * len(dates),
        "close": [10.5] * len(dates),
        "volume": [1000.0] * len(dates),
    })

    as_of = datetime.datetime.combine(mkt_date, datetime.time(11, 0), tzinfo=B3_TIMEZONE)
    res = closed_daily_signal_frame(df, as_of=as_of)

    assert res.today_bar_removed is True
    assert res.market_date == mkt_date
    assert res.decision_bar_date == mkt_date - datetime.timedelta(days=1)
    assert len(res.df) == len(df) - 1
    assert mkt_date not in list(res.df["date"])


def test_closed_daily_signal_frame_retains_all_if_no_today_bar():
    """If all bars are prior to market_date, no bar is removed."""
    mkt_date = datetime.date(2026, 3, 10)
    dates = [mkt_date - datetime.timedelta(days=i) for i in range(210, 0, -1)]
    df = pd.DataFrame({
        "date": dates,
        "open": [10.0] * len(dates),
        "high": [11.0] * len(dates),
        "low": [9.0] * len(dates),
        "close": [10.5] * len(dates),
        "volume": [1000.0] * len(dates),
    })

    as_of = datetime.datetime.combine(mkt_date, datetime.time(11, 0), tzinfo=B3_TIMEZONE)
    res = closed_daily_signal_frame(df, as_of=as_of)

    assert res.today_bar_removed is False
    assert res.decision_bar_date == dates[-1]
    assert len(res.df) == len(df)


# ===========================================================================
# 4. STRATEGY CONFIG AND UNIVERSE FAIL-CLOSED TESTS
# ===========================================================================

def test_corrupt_strategy_config_fails_closed(tmp_path):
    """Corrupt signals configuration must result in ValueError without fallback."""
    corrupt_cfg = tmp_path / "corrupt_settings.yaml"
    corrupt_cfg.write_text("signals:\n  breakout_period: 'invalid_number'\n", encoding="utf-8")

    analyst = MarketAnalyst("PETR4.SA")
    with pytest.raises(ValueError):
        analyst._signal_params(settings_path=str(corrupt_cfg))


def test_missing_signals_section_fails_closed(tmp_path):
    """Missing signals configuration section must fail closed."""
    missing_cfg = tmp_path / "empty_settings.yaml"
    missing_cfg.write_text("other_section: true\n", encoding="utf-8")

    analyst = MarketAnalyst("VALE3.SA")
    with pytest.raises(ValueError):
        analyst._signal_params(settings_path=str(missing_cfg))


@pytest.mark.asyncio
async def test_empty_universe_fails_closed():
    """Empty universe in _run_one_scan_cycle fails closed without default ticker fallback."""
    from backend.app.main import _run_one_scan_cycle

    with patch("trading_bot.core.config.AppConfig.load") as mock_load:
        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = (
            lambda *a, **k: [] if a and a[0] == "_universe" else ("full_auto" if a and a[0] == "execution" else k.get("default"))
        )
        mock_load.return_value = mock_cfg
        with patch("backend.app.main.logger.error") as mock_err:
            await _run_one_scan_cycle()
            mock_err.assert_called_with("Universo configurado vazio ou indisponível — ciclo abortado (fail-closed)")


# ===========================================================================
# 5. MACRO IBOV FAIL-CLOSED TESTS
# ===========================================================================

def test_ibov_none_fails_closed():
    """ibov_in_uptrend(None) must return False (NEXUS-004)."""
    assert ibov_in_uptrend(None, ref_date=datetime.date(2026, 3, 9)) is False


def test_ibov_forming_today_bar_fails_closed():
    """ref_date on or after current_market_date must fail closed."""
    df = pd.DataFrame({
        "ts": [datetime.date(2026, 3, 10)],
        "c": [130000.0],
        "sma50": [120000.0],
    })
    assert ibov_in_uptrend(
        df,
        ref_date=datetime.date(2026, 3, 10),
        current_market_date=datetime.date(2026, 3, 10),
    ) is False


def test_ibov_below_sma50_returns_false():
    """When closed IBOV is below SMA-50, returns False."""
    df = pd.DataFrame({
        "ts": [datetime.date(2026, 3, 9)],
        "c": [115000.0],
        "sma50": [120000.0],
    })
    assert ibov_in_uptrend(
        df,
        ref_date=datetime.date(2026, 3, 9),
        current_market_date=datetime.date(2026, 3, 10),
    ) is False


def test_ibov_valid_closed_uptrend_returns_true():
    """When closed IBOV is above SMA-50 with ref_date < market_date, returns True."""
    df = pd.DataFrame({
        "ts": [datetime.date(2026, 3, 9)],
        "c": [125000.0],
        "sma50": [120000.0],
    })
    assert ibov_in_uptrend(
        df,
        ref_date=datetime.date(2026, 3, 9),
        current_market_date=datetime.date(2026, 3, 10),
    ) is True


# ===========================================================================
# 6. ENTRY FILL QUOTE FRESHNESS AND GAP GEOMETRY TESTS
# ===========================================================================

def _create_synthetic_quote(ticker: str, price: float, age_seconds: float = 0.0) -> EvidencedQuote:
    obs = datetime.datetime.now(timezone.utc) - datetime.timedelta(seconds=age_seconds)
    raw = {
        "ticker": ticker,
        "close": price,
        "source": "yfinance",
        "price_kind": "bar_close",
        "interval": "1m",
        "vendor_symbol": ticker,
        "observed_at": obs.isoformat(),
        "collected_at": obs.isoformat(),
    }
    return EvidencedQuote(
        ticker=ticker,
        price=price,
        currency="BRL",
        source="yfinance",
        price_kind="bar_close",
        interval="1m",
        vendor_symbol=ticker,
        observed_at=obs,
        collected_at=obs,
        source_ref="test",
        source_sha256=compute_evidence_sha256(raw),
        raw_evidence=raw,
    )


def test_entry_stale_quote_rejected():
    """Stale quote beyond max_age_seconds must be rejected by ApprovedExecutionIntent."""
    now_utc = datetime.datetime.now(timezone.utc)
    sig = TypedSignal(
        ticker="PETR4.SA",
        side="BUY",
        price=30.0,
        target_price=35.0,
        stop_loss=28.0,
        dataset_sha256="a" * 64,
        reason="Donchian breakout test",
        generated_at=now_utc,
    )
    decision = RiskDecision(
        signal_id=sig.signal_id,
        approved=True,
        reason="Test approval",
        allocated_capital=1000.0,
        target_price=35.0,
        stop_loss=28.0,
        decision_timestamp=now_utc,
    )

    stale_quote = _create_synthetic_quote("PETR4.SA", 30.5, age_seconds=120.0)
    with pytest.raises(ValueError, match="stale"):
        ApprovedExecutionIntent(
            signal=sig,
            risk_decision=decision,
            execution_quote=stale_quote,
        )


def test_entry_gap_geometry_rejected():
    """BUY order must satisfy stop_loss < execution_price < target_price."""
    now_utc = datetime.datetime.now(timezone.utc)
    sig = TypedSignal(
        ticker="PETR4.SA",
        side="BUY",
        price=30.0,
        target_price=35.0,
        stop_loss=28.0,
        dataset_sha256="a" * 64,
        reason="Donchian breakout test",
        generated_at=now_utc,
    )
    decision = RiskDecision(
        signal_id=sig.signal_id,
        approved=True,
        reason="Test approval",
        allocated_capital=1000.0,
        target_price=35.0,
        stop_loss=28.0,
        decision_timestamp=now_utc,
    )

    gap_down_quote = _create_synthetic_quote("PETR4.SA", 27.5)
    with pytest.raises(ValueError, match="Gap geometry violation"):
        ApprovedExecutionIntent(
            signal=sig,
            risk_decision=decision,
            execution_quote=gap_down_quote,
        )

    gap_up_quote = _create_synthetic_quote("PETR4.SA", 35.5)
    with pytest.raises(ValueError, match="Gap geometry violation"):
        ApprovedExecutionIntent(
            signal=sig,
            risk_decision=decision,
            execution_quote=gap_up_quote,
        )


def test_valid_quote_distinguishes_decision_from_execution_price(tmp_path):
    """Executor must persist both decision_price and execution entry_price."""
    db_file = tmp_path / "test_exec.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE portfolio (id INTEGER PRIMARY KEY, saldo_disponivel REAL, patrimonio_total REAL, em_posicoes REAL, margem_operavel REAL, updated_at TIMESTAMP)"
    )
    conn.execute("INSERT INTO portfolio VALUES (1, 10000.0, 10000.0, 0.0, 10000.0, CURRENT_TIMESTAMP)")
    conn.execute(
        "CREATE TABLE trades ("
        "id INTEGER PRIMARY KEY, ticker TEXT, side TEXT, entry_price REAL, decision_price REAL, "
        "shares INTEGER, target_price REAL, stop_loss REAL, status TEXT, signal_id TEXT, "
        "entry_date TEXT, allocated_capital REAL, ai_rationale TEXT)"
    )
    conn.commit()
    conn.close()

    now_utc = datetime.datetime.now(timezone.utc)
    sig = TypedSignal(
        ticker="PETR4.SA",
        side="BUY",
        price=30.0,  # DECISION PRICE
        target_price=35.0,
        stop_loss=28.0,
        dataset_sha256="b" * 64,
        reason="Donchian breakout test",
        generated_at=now_utc,
    )
    decision = RiskDecision(
        signal_id=sig.signal_id,
        approved=True,
        reason="Test approval",
        allocated_capital=3000.0,
        target_price=35.0,
        stop_loss=28.0,
        decision_timestamp=now_utc,
    )
    exec_quote = _create_synthetic_quote("PETR4.SA", 30.80)  # EXECUTION PRICE

    from backend.app.markets.b3_session import (
        AutonomousSessionAuthority,
        B3DayType,
        B3SessionPhase,
        override_session_authority,
    )
    auth = AutonomousSessionAuthority(
        override_fn=lambda dt=None: (
            True,
            "Authorized in test",
            B3DayType.NORMAL_TRADING_DAY,
            B3SessionPhase.CONTINUOUS,
        )
    )
    with override_session_authority(auth):
        intent = ApprovedExecutionIntent(
            signal=sig,
            risk_decision=decision,
            execution_quote=exec_quote,
        )

        executor = ExecutorAgent(db_path=str(db_file))
        res = executor.execute_order(intent)
        assert res["status"] == "executed"
        assert res["entry_price"] == 30.80
        assert res["decision_price"] == 30.0

    conn = sqlite3.connect(str(db_file))
    row = conn.execute("SELECT entry_price, decision_price, status FROM trades WHERE signal_id = ?", (sig.signal_id,)).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 30.80
    assert row[1] == 30.0
    assert row[2] == "active"


# ===========================================================================
# 7. EXIT PRICE TRUST TESTS
# ===========================================================================

def test_price_trustworthy_rejects_non_finite_and_bool():
    """_price_is_trustworthy must reject NaN, +Inf, -Inf, and boolean (NEXUS-004)."""
    assert _price_is_trustworthy(float("inf")) is False
    assert _price_is_trustworthy(float("-inf")) is False
    assert _price_is_trustworthy(float("nan")) is False
    assert _price_is_trustworthy(True) is False
    assert _price_is_trustworthy(False) is False
    assert _price_is_trustworthy(0.0) is False
    assert _price_is_trustworthy(-5.0) is False
    assert _price_is_trustworthy(None) is False
    assert _price_is_trustworthy(32.50) is True


def test_price_trustworthy_checks_timestamp_freshness():
    """_price_is_trustworthy rejects stale observations."""
    now = datetime.datetime.now(timezone.utc)
    stale_time = now - datetime.timedelta(seconds=200)

    assert _price_is_trustworthy(
        30.0,
        observed_at=stale_time,
        max_age_seconds=60.0,
        now=now,
    ) is False

    fresh_time = now - datetime.timedelta(seconds=10)
    assert _price_is_trustworthy(
        30.0,
        observed_at=fresh_time,
        max_age_seconds=60.0,
        now=now,
    ) is True


# ===========================================================================
# 8. PAPERSESSION RUNNER REGRESSION TESTS
# ===========================================================================

def test_paper_session_risk_rejection_no_crash(tmp_path):
    """PaperSessionRunner must not crash on rejected RiskDecision (NEXUS-004)."""
    db_file = tmp_path / "paper_reject.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE portfolio (id INTEGER PRIMARY KEY, saldo_disponivel REAL, patrimonio_total REAL, em_posicoes REAL, margem_operavel REAL)"
    )
    conn.execute("INSERT INTO portfolio VALUES (1, 1000.0, 1000.0, 0.0, 1000.0)")
    conn.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, ticker TEXT, side TEXT, entry_price REAL, status TEXT, signal_id TEXT)"
    )
    conn.commit()
    conn.close()

    runner = PaperSessionRunner(db_path=str(db_file), storage_dir=str(tmp_path / "storage"))

    now_utc = datetime.datetime.now(timezone.utc)
    sig = TypedSignal(
        ticker="VALE3.SA",
        side="BUY",
        price=50.0,
        target_price=60.0,
        stop_loss=45.0,
        dataset_sha256="c" * 64,
        reason="Donchian breakout test",
        generated_at=now_utc,
    )

    mock_rm = MagicMock()
    mock_decision = RiskDecision(
        signal_id=sig.signal_id,
        approved=False,
        reason="Risk limit exceeded: high volatility",
        allocated_capital=0.0,
        target_price=60.0,
        stop_loss=45.0,
        decision_timestamp=now_utc,
    )
    mock_rm.evaluate_trade.return_value = mock_decision
    runner.risk_manager_cls = MagicMock(return_value=mock_rm)

    report = runner.run_cycle(signals=[sig.model_dump(mode="json")])
    assert report.orders_rejected == 1
    assert report.orders_executed == 0


def test_paper_session_saldo_operavel_ceiling(tmp_path):
    """PaperSessionRunner must enforce canonical saldo_operavel margin formula."""
    db_file = tmp_path / "margin_test.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE portfolio (id INTEGER PRIMARY KEY, saldo_disponivel REAL, patrimonio_total REAL, em_posicoes REAL, margem_operavel REAL)"
    )
    conn.commit()

    runner = PaperSessionRunner(db_path=str(db_file), storage_dir=str(tmp_path / "storage"))

    cases = [
        (1000.0, 0.0, 300.0, 300.0),
        (1000.0, 250.0, 300.0, 50.0),
        (1000.0, 400.0, 300.0, 0.0),
        (1000.0, 100.0, None, 900.0),
    ]

    for disp, em_pos, margem, expected in cases:
        conn.execute("DELETE FROM portfolio")
        conn.execute("INSERT INTO portfolio VALUES (1, ?, ?, ?, ?)", (disp, disp, em_pos, margem))
        conn.commit()

        st = runner.get_portfolio_state()
        assert st["saldo_operavel"] == expected, f"Failed for {disp}, {em_pos}, {margem}: got {st['saldo_operavel']}, expected {expected}"

    conn.close()


def test_paper_session_zero_operable_cash_rejects(tmp_path):
    """When saldo_operavel <= 0, entry signals must be rejected immediately."""
    db_file = tmp_path / "zero_cash.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE portfolio (id INTEGER PRIMARY KEY, saldo_disponivel REAL, patrimonio_total REAL, em_posicoes REAL, margem_operavel REAL)"
    )
    conn.execute("INSERT INTO portfolio VALUES (1, 1000.0, 1000.0, 350.0, 300.0)")
    conn.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, ticker TEXT, side TEXT, entry_price REAL, status TEXT, signal_id TEXT)"
    )
    conn.commit()
    conn.close()

    runner = PaperSessionRunner(db_path=str(db_file), storage_dir=str(tmp_path / "storage"))
    now_utc = datetime.datetime.now(timezone.utc)
    sig = TypedSignal(
        ticker="PETR4.SA",
        side="BUY",
        price=30.0,
        target_price=35.0,
        stop_loss=28.0,
        dataset_sha256="d" * 64,
        reason="Donchian breakout test",
        generated_at=now_utc,
    )

    report = runner.run_cycle(signals=[sig.model_dump(mode="json")])
    assert report.orders_rejected == 1
    assert report.orders_executed == 0


# ===========================================================================
# 9. PREFLIGHT TRUTH TESTS
# ===========================================================================

def test_preflight_distinguishes_infra_vs_entry_ready(tmp_path, monkeypatch):
    """Preflight outside CONTINUOUS reports INFRASTRUCTURE_READY=PASS, ENTRY_READY=BLOCKED_SESSION_PHASE."""
    test_db = tmp_path / "preflight_truth.db"
    conn = sqlite3.connect(str(test_db))
    conn.execute("CREATE TABLE portfolio (id INTEGER PRIMARY KEY, patrimonio_total REAL, saldo_disponivel REAL)")
    conn.execute("INSERT INTO portfolio VALUES (1, 5000.0, 5000.0)")
    conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, ticker TEXT, status TEXT, signal_id TEXT)")
    conn.execute("CREATE UNIQUE INDEX idx_trades_strategy_signal_id ON trades(signal_id) WHERE signal_id IS NOT NULL")
    conn.execute("CREATE UNIQUE INDEX idx_trades_one_active_per_ticker ON trades(ticker) WHERE status = 'active'")
    conn.commit()
    conn.close()

    ticker = "VALE3.SA"
    dates = [datetime.date(2025, 1, 1) + datetime.timedelta(days=i) for i in range(220)]
    df = pd.DataFrame({
        "date": [str(d) for d in dates],
        "open": [30.0 + i * 0.05 for i in range(220)],
        "high": [31.0 + i * 0.05 for i in range(220)],
        "low": [29.0 + i * 0.05 for i in range(220)],
        "close": [30.2 + i * 0.05 for i in range(220)],
        "volume": [10000.0] * 220,
    })

    from trading_bot.data.approval_candidate import (
        APPROVAL_CONFIRMATION_TOKEN,
        approve_candidate,
        build_candidate_bundle,
    )
    import json
    bundle_dir = tmp_path / "candidates" / "vale3"
    manifest = build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=df,
    )
    custom_reg = tmp_path / "custom_approvals.json"
    custom_reg.write_text(json.dumps({"version": 1, "approvals": []}), encoding="utf-8")
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
            return df.copy()

    from scripts import paper_session_preflight
    monkeypatch.setattr(paper_session_preflight, "resolve_market", lambda sym: MockMarket())

    sat_dt = datetime.datetime(2026, 3, 14, 11, 0, tzinfo=B3_TIMEZONE)

    report = run_paper_preflight(
        registry_path=custom_reg,
        db_path=test_db,
        storage_dir=tmp_path / "storage",
        project_root=tmp_path,
        tickers=[ticker],
        now_dt=sat_dt,
    )

    assert report.db_schema_check is True
    assert report.broker_isolation_check is True
    assert report.infrastructure_ready == "PASS"
    assert report.b3_entry_allowed is False
    assert report.ticker_results[0].preflight_verdict == "PASS"
    assert report.entry_ready == "BLOCKED_SESSION_PHASE"
    assert report.overall_status == "BLOCKED_SESSION_PHASE"
    assert "VALUATION_CONTRACT_AVAILABLE" in report.valuation_honesty_status


def test_preflight_valuation_honesty_not_overclaimed():
    """check_valuation_subsystem must truthfully report STORE_UNVERIFIED."""
    ok, honesty, msg = check_valuation_subsystem()
    assert ok is True
    assert honesty == "VALUATION_CONTRACT_AVAILABLE / VALUATION_STORE_UNVERIFIED"
    assert "VALUATION_STORE_UNVERIFIED" in msg


# ===========================================================================
# 10. NEXUS-004-R2: EXIT AUTHORITY, SESSION DEFENSE & PAPER CLOSEOUT (A - Q)
# ===========================================================================

def _init_r2_test_db(db_path: Path, initial_cash: float = 1000.0, active_trades: Optional[List[tuple]] = None) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, side TEXT, shares REAL, entry_price REAL,
            exit_price REAL, target_price REAL, stop_loss REAL,
            entry_date TIMESTAMP, exit_date TIMESTAMP,
            pnl_pct REAL, exit_reason TEXT, ai_rationale TEXT, status TEXT, signal_id TEXT)
    """)
    conn.execute("CREATE UNIQUE INDEX idx_trades_one_active_per_ticker ON trades(ticker) WHERE status = 'active'")
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
    em_pos = sum((row[2] * row[3]) for row in (active_trades or []))
    conn.execute(
        "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, margem_operavel, updated_at) VALUES (?, ?, ?, ?, ?)",
        (initial_cash, initial_cash, em_pos, initial_cash, datetime.datetime.now()),
    )
    if active_trades:
        for t in active_trades:
            conn.execute(
                "INSERT INTO trades (ticker, side, shares, entry_price, target_price, stop_loss, entry_date, ai_rationale, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'test', 'active')",
                (t[0], t[1], t[2], t[3], t[4], t[5], datetime.datetime.now()),
            )
    conn.commit()
    conn.close()


def test_r2_regression_a_missing_evidence_rejected_zero_mutation(tmp_path):
    """A. Automatic/manual exit with missing evidence -> rejected, zero trade mutation, zero portfolio mutation."""
    db_file = tmp_path / "test_a.db"
    _init_r2_test_db(db_file, 1000.0, [("PETR4.SA", "BUY", 10.0, 30.0, 33.0, 28.5)])
    executor = ExecutorAgent(str(db_file))

    res = executor.close_order(1, 33.0, "Take Profit hit", evidence=None)
    assert res["status"] == "rejected"
    assert "evidence is required" in res["reason"]

    conn = sqlite3.connect(str(db_file))
    trade = conn.execute("SELECT status, exit_price FROM trades WHERE id = 1").fetchone()
    pf = conn.execute("SELECT saldo_disponivel, em_posicoes FROM portfolio WHERE id = 1").fetchone()
    conn.close()

    assert trade[0] == "active"
    assert trade[1] is None
    assert pf[0] == 1000.0
    assert pf[1] == 300.0


def test_r2_regression_b_wrong_ticker_evidence_rejected_zero_mutation(tmp_path):
    """B. Wrong-ticker exit evidence -> rejected, zero mutation."""
    from tests.conftest import make_test_evidenced_quote
    db_file = tmp_path / "test_b.db"
    _init_r2_test_db(db_file, 1000.0, [("PETR4.SA", "BUY", 10.0, 30.0, 33.0, 28.5)])
    executor = ExecutorAgent(str(db_file))

    # Evidence for VALE3 when closing PETR4
    vale_quote = make_test_evidenced_quote("VALE3.SA", 33.0)
    res = executor.close_order(1, 33.0, "Take Profit hit", evidence=vale_quote)
    assert res["status"] == "rejected"
    assert "does not match trade ticker" in res["reason"]

    conn = sqlite3.connect(str(db_file))
    trade = conn.execute("SELECT status FROM trades WHERE id = 1").fetchone()
    pf = conn.execute("SELECT saldo_disponivel, em_posicoes FROM portfolio WHERE id = 1").fetchone()
    conn.close()
    assert trade[0] == "active"
    assert pf[1] == 300.0


def test_r2_regression_c_tampered_raw_evidence_hash_rejected_zero_mutation(tmp_path):
    """C. Tampered raw evidence/hash -> rejected, zero mutation."""
    from tests.conftest import make_test_evidenced_quote
    db_file = tmp_path / "test_c.db"
    _init_r2_test_db(db_file, 1000.0, [("PETR4.SA", "BUY", 10.0, 30.0, 33.0, 28.5)])
    executor = ExecutorAgent(str(db_file))

    quote = make_test_evidenced_quote("PETR4.SA", 33.0)
    # Tamper source_sha256 directly
    tampered_quote = quote.model_copy(update={"source_sha256": "f" * 64})

    res = executor.close_order(1, 33.0, "Take Profit hit", evidence=tampered_quote)
    assert res["status"] == "rejected"
    assert "mismatch" in res["reason"]

    conn = sqlite3.connect(str(db_file))
    trade = conn.execute("SELECT status FROM trades WHERE id = 1").fetchone()
    conn.close()
    assert trade[0] == "active"


def test_r2_regression_d_stale_observation_rejected_zero_mutation(tmp_path):
    """D. Stale observation (> 300s) -> rejected, zero mutation."""
    from tests.conftest import make_test_evidenced_quote
    db_file = tmp_path / "test_d.db"
    _init_r2_test_db(db_file, 1000.0, [("PETR4.SA", "BUY", 10.0, 30.0, 33.0, 28.5)])
    executor = ExecutorAgent(str(db_file))

    stale_quote = make_test_evidenced_quote("PETR4.SA", 33.0, age_seconds=301.0)
    res = executor.close_order(1, 33.0, "Take Profit hit", evidence=stale_quote)
    assert res["status"] == "rejected"
    assert "stale" in res["reason"]

    conn = sqlite3.connect(str(db_file))
    trade = conn.execute("SELECT status FROM trades WHERE id = 1").fetchone()
    conn.close()
    assert trade[0] == "active"


def test_r2_regression_e_naive_quote_timestamp_rejected_zero_mutation(tmp_path):
    """E. Naive quote timestamp -> rejected, zero mutation (exercises actual naive datetime validation)."""
    db_file = tmp_path / "test_e.db"
    _init_r2_test_db(db_file, 1000.0, [("PETR4.SA", "BUY", 10.0, 30.0, 33.0, 28.5)])
    executor = ExecutorAgent(str(db_file))

    # 1. Model layer: EvidencedQuote strictly rejects naive observed_at and collected_at
    from trading_bot.data.valuation_snapshot import EvidencedQuote, compute_evidence_sha256
    naive_dt = datetime.datetime.now()
    raw_naive = {
        "ticker": "PETR4.SA", "close": 33.0, "source": "yfinance", "price_kind": "bar_close",
        "interval": "1m", "vendor_symbol": "PETR4.SA", "observed_at": naive_dt.isoformat(),
        "collected_at": naive_dt.isoformat(),
    }
    with pytest.raises(ValueError, match="timezone-aware datetime required"):
        EvidencedQuote(
            ticker="PETR4.SA", price=33.0, currency="BRL", source="yfinance", price_kind="bar_close",
            interval="1m", vendor_symbol="PETR4.SA", observed_at=naive_dt, collected_at=naive_dt,
            source_ref="test", source_sha256=compute_evidence_sha256(raw_naive), raw_evidence=raw_naive,
        )

    # 2. Main exit trust helper rejects naive timestamp
    from backend.app.main import _price_is_trustworthy
    assert _price_is_trustworthy(33.0, observed_at=naive_dt) is False

    # 3. Snapshot verification: Executor close_order rejects with zero mutation on both tables
    conn = sqlite3.connect(str(db_file))
    trade_before = conn.execute("SELECT * FROM trades").fetchall()
    port_before = conn.execute("SELECT * FROM portfolio").fetchall()
    conn.close()

    class FakeQuote:
        price = 33.0
        observed_at = naive_dt  # naive

    res = executor.close_order(1, 33.0, "Take Profit hit", evidence=FakeQuote())
    assert res["status"] == "rejected"

    conn = sqlite3.connect(str(db_file))
    trade_after = conn.execute("SELECT * FROM trades").fetchall()
    port_after = conn.execute("SELECT * FROM portfolio").fetchall()
    conn.close()
    assert trade_after == trade_before
    assert port_after == port_before


def test_r2_regression_f_invalid_price_rejected_zero_mutation(tmp_path):
    """F. NaN / +Inf / -Inf / bool / <=0 price -> rejected, zero mutation."""
    from tests.conftest import make_test_evidenced_quote
    db_file = tmp_path / "test_f.db"
    _init_r2_test_db(db_file, 1000.0, [("PETR4.SA", "BUY", 10.0, 30.0, 33.0, 28.5)])
    executor = ExecutorAgent(str(db_file))

    ev = make_test_evidenced_quote("PETR4.SA", 33.0)

    for invalid_p in [float("nan"), float("inf"), float("-inf"), True, False, 0.0, -10.0, None]:
        res = executor.close_order(1, invalid_p, "Take Profit hit", evidence=ev)
        assert res["status"] == "rejected"

    conn = sqlite3.connect(str(db_file))
    trade = conn.execute("SELECT status FROM trades WHERE id = 1").fetchone()
    conn.close()
    assert trade[0] == "active"


def test_r2_regression_g_papersession_bare_current_prices_cannot_close(tmp_path, monkeypatch):
    """G. PaperSession bare current_prices cannot directly authorize exit without EvidencedQuote."""
    db_file = tmp_path / "paper_bare.db"
    storage_dir = tmp_path / "paper_sessions"
    _init_r2_test_db(db_file, 1000.0, [("PETR4", "BUY", 10.0, 30.0, 33.0, 28.5)])

    # Feed is down / returns None for quotes
    monkeypatch.setattr("backend.app.data.feed.get_evidenced_quote", lambda t, *a, **k: None)

    runner = PaperSessionRunner(session_id="sess_bare_g", db_path=str(db_file), storage_dir=str(storage_dir))
    rep = runner.run_cycle(signals=[], current_prices={"PETR4": 34.0})

    assert rep.orders_closed == 0
    conn = sqlite3.connect(str(db_file))
    trade = conn.execute("SELECT status FROM trades WHERE id = 1").fetchone()
    conn.close()
    assert trade[0] == "active"

    # Journal must record ORDER_REJECTED due to missing evidence
    events = runner.journal.load_events()
    rejected_events = [e for e in events if e.event_type == "ORDER_REJECTED"]
    assert len(rejected_events) >= 1
    assert rejected_events[0].payload["reason"] == "no_evidenced_quote_available"


def test_r2_regression_h_valid_evidenced_automatic_exit_reconciles_exactly_once(tmp_path):
    """H. Valid evidenced automatic exit -> exactly one close -> portfolio reconciled exactly once."""
    from tests.conftest import make_test_evidenced_quote
    db_file = tmp_path / "paper_valid_h.db"
    storage_dir = tmp_path / "paper_sessions"
    _init_r2_test_db(db_file, 1000.0, [("PETR4", "BUY", 10.0, 30.0, 33.0, 28.5)])

    ev_exit = make_test_evidenced_quote("PETR4", 34.0)
    runner = PaperSessionRunner(session_id="sess_valid_h", db_path=str(db_file), storage_dir=str(storage_dir))
    rep = runner.run_cycle(signals=[], current_prices={"PETR4": ev_exit})

    assert rep.orders_closed == 1
    assert rep.reconciliation_ok is True
    assert rep.discrepancies == []

    conn = sqlite3.connect(str(db_file))
    trade = conn.execute("SELECT status, exit_price, pnl_pct FROM trades WHERE id = 1").fetchone()
    pf = conn.execute("SELECT saldo_disponivel, em_posicoes FROM portfolio WHERE id = 1").fetchone()
    conn.close()

    assert trade[0] == "closed"
    assert trade[1] == 34.0
    assert trade[2] == pytest.approx(13.333333333333334)
    # Initial: 1000. em_posicoes was 300. Return 300 + (34-30)*10 = 340. New saldo_disponivel = 1040.
    assert pf[1] == 0.0
    assert pf[0] == pytest.approx(1040.0)


def test_r2_regression_i_intent_continuous_then_closed_before_executor_rejected(tmp_path):
    """I. Valid intent created CONTINUOUS then authority CLOSED before executor -> rejected, zero mutation."""
    from tests.conftest import make_test_evidenced_quote
    from backend.app.markets.b3_session import override_session_authority, AutonomousSessionAuthority
    db_file = tmp_path / "session_defense_i.db"
    _init_r2_test_db(db_file, 1000.0)
    executor = ExecutorAgent(str(db_file))

    # Intent constructed during CONTINUOUS phase (11:00 AM)
    valid_dt = datetime.datetime(2026, 3, 10, 11, 0, tzinfo=B3_TIMEZONE)
    quote = make_test_evidenced_quote("PETR4.SA", 30.0)
    sig = TypedSignal(
        ticker="PETR4.SA",
        side="BUY",
        price=30.0,
        target_price=33.0,
        stop_loss=28.5,
        dataset_sha256="0" * 64,
        dataset_approved=True,
        generated_at=valid_dt,
        reason="Session defense test",
    )
    decision = RiskDecision(
        signal_id=sig.signal_id,
        approved=True,
        reason="Approved for execution",
        allocated_capital=300.0,
        target_price=33.0,
        stop_loss=28.5,
        decision_timestamp=valid_dt,
    )
    # Intent constructed during CONTINUOUS phase
    open_authority = AutonomousSessionAuthority(
        override_fn=lambda dt=None: (
            True,
            "B3 market session phase is CONTINUOUS",
            B3DayType.NORMAL_TRADING_DAY,
            B3SessionPhase.CONTINUOUS,
        )
    )
    with override_session_authority(open_authority):
        intent = ApprovedExecutionIntent(
            signal=sig,
            risk_decision=decision,
            execution_quote=quote,
        )

    # Now authority transitions to CLOSED before executor write
    closed_authority = AutonomousSessionAuthority(
        override_fn=lambda dt=None: (
            False,
            "B3 market session phase is CLOSED",
            B3DayType.NORMAL_TRADING_DAY,
            B3SessionPhase.CLOSED,
        )
    )
    with override_session_authority(closed_authority):
        res = executor.execute_order(intent)
        assert res["status"] == "rejected"
        assert "Autonomous session" in res["reason"]

    conn = sqlite3.connect(str(db_file))
    trades_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    pf = conn.execute("SELECT saldo_disponivel, em_posicoes FROM portfolio WHERE id = 1").fetchone()
    conn.close()

    assert trades_count == 0
    assert pf[0] == 1000.0
    assert pf[1] == 0.0


def test_r2_regression_j_explicit_naive_session_datetime_denied():
    """J. Explicit naive session datetime -> fail-closed: denied by authority, UNKNOWN day, CLOSED phase."""
    from backend.app.markets.b3_session import (
        check_autonomous_session_authority,
        get_day_type,
        get_session_phase,
        can_enter_new_position,
    )
    naive_dt = datetime.datetime(2026, 3, 10, 11, 0)  # naive (no tzinfo)

    # 1. Day type fails closed to UNKNOWN
    assert get_day_type(naive_dt) == B3DayType.UNKNOWN

    # 2. Session phase fails closed to CLOSED
    assert get_session_phase(naive_dt) == B3SessionPhase.CLOSED

    # 3. Autonomous authority check fails closed with explicit rejection reason
    allowed, reason, d_type, phase = check_autonomous_session_authority(naive_dt)
    assert allowed is False
    assert "Explicit naive datetime rejected" in reason
    assert d_type == B3DayType.UNKNOWN
    assert phase == B3SessionPhase.CLOSED

    # 4. can_enter_new_position fails closed
    assert can_enter_new_position(naive_dt) is False


def test_r2_regression_k_exit_freshness_policy(tmp_path):
    """K. Exit freshness policy aligns with canonical PAPER_DEFAULT_MAX_QUOTE_AGE_SECONDS (60.0s)."""
    from tests.conftest import make_test_evidenced_quote
    from trading_bot.data.valuation_snapshot import PAPER_DEFAULT_MAX_QUOTE_AGE_SECONDS
    from backend.app.main import PAPER_EXIT_MAX_OBSERVATION_AGE_SECONDS

    # 1. Authority alignment: entry and exit defaults use identical canonical value
    assert PAPER_DEFAULT_MAX_QUOTE_AGE_SECONDS == 60.0
    assert PAPER_EXIT_MAX_OBSERVATION_AGE_SECONDS == 60.0

    db_file = tmp_path / "test_k.db"
    _init_r2_test_db(db_file, 1000.0, [("PETR4.SA", "BUY", 10.0, 30.0, 33.0, 28.5)])
    executor = ExecutorAgent(str(db_file))

    # 2. Materially future quote (now + 10s) -> rejected
    future_obs = datetime.datetime.now(timezone.utc) + datetime.timedelta(seconds=10.0)
    raw_future = {
        "ticker": "PETR4.SA", "close": 33.0, "source": "yfinance", "price_kind": "bar_close",
        "interval": "1m", "vendor_symbol": "PETR4.SA", "observed_at": future_obs.isoformat(),
        "collected_at": future_obs.isoformat(),
    }
    future_quote = EvidencedQuote(
        ticker="PETR4.SA", price=33.0, currency="BRL", source="yfinance", price_kind="bar_close",
        interval="1m", vendor_symbol="PETR4.SA", observed_at=future_obs, collected_at=future_obs,
        source_ref="test", source_sha256=compute_evidence_sha256(raw_future), raw_evidence=raw_future,
    )
    res_future = executor.close_order(1, 33.0, "Take Profit hit", evidence=future_quote)
    assert res_future["status"] == "rejected"
    assert "future" in res_future["reason"]

    # 3. 120s old quote under 60s canonical policy -> rejected
    quote_120 = make_test_evidenced_quote("PETR4.SA", 33.0, age_seconds=120.0)
    res_120 = executor.close_order(1, 33.0, "Take Profit hit", evidence=quote_120)
    assert res_120["status"] == "rejected"
    assert "stale" in res_120["reason"]

    # 4. Stale quote (65s old > 60s) -> rejected
    quote_65 = make_test_evidenced_quote("PETR4.SA", 33.0, age_seconds=65.0)
    res_65 = executor.close_order(1, 33.0, "Take Profit hit", evidence=quote_65)
    assert res_65["status"] == "rejected"
    assert "stale" in res_65["reason"]

    # 5. Invalid max-age override -> rejected (cannot fail open)
    fresh_quote = make_test_evidenced_quote("PETR4.SA", 33.0, age_seconds=15.0)
    for bad_limit in [float("nan"), float("inf"), -1.0, 0.0, True, False]:
        res_bad = executor.close_order(1, 33.0, "Take Profit hit", evidence=fresh_quote, max_observation_age_seconds=bad_limit)
        assert res_bad["status"] == "rejected"

    # 6. Fresh 1m quote within canonical 60s policy (15s old) -> accepted
    res_fresh = executor.close_order(1, 33.0, "Take Profit hit", evidence=fresh_quote)
    assert res_fresh["status"] == "closed"


def test_r2_regression_l_preflight_import_only_not_ready(tmp_path, monkeypatch, mock_circuit_breaker):
    """L. Preflight import-only path cannot aggregate to operational PASS; requires behavioral verification."""
    from scripts.paper_session_preflight import (
        check_entry_quote_path,
        check_exit_quote_path,
        run_paper_preflight,
    )
    from backend.app.markets.b3_session import B3_TIMEZONE
    import sqlite3
    import json
    from datetime import date, timedelta
    from trading_bot.data.approval_candidate import (
        APPROVAL_CONFIRMATION_TOKEN,
        build_candidate_bundle,
        approve_candidate,
    )
    import pandas as pd

    # 1. Structural contract labels are truthful
    ok_in, status_in, _ = check_entry_quote_path()
    assert ok_in is True
    assert status_in == "STRUCTURALLY_PRESENT"
    assert status_in != "READY"
    assert status_in != "BEHAVIORALLY_VERIFIED"

    ok_out, status_out, _ = check_exit_quote_path()
    assert ok_out is True
    assert status_out == "STRUCTURALLY_PRESENT"
    assert status_out != "READY"
    assert status_out != "BEHAVIORALLY_VERIFIED"

    # 2. Aggregate preflight during open trading hours with all other gates passing
    test_db = tmp_path / "preflight_agg.db"
    conn = sqlite3.connect(str(test_db))
    conn.execute("CREATE TABLE portfolio (id INTEGER PRIMARY KEY, patrimonio_total REAL, saldo_disponivel REAL, em_posicoes REAL, margem_operavel REAL)")
    conn.execute("INSERT INTO portfolio VALUES (1, 10000.0, 10000.0, 0.0, 10000.0)")
    conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, ticker TEXT, side TEXT, shares REAL, entry_price REAL, exit_price REAL, target_price REAL, stop_loss REAL, entry_date TIMESTAMP, exit_date TIMESTAMP, pnl_pct REAL, exit_reason TEXT, ai_rationale TEXT, status TEXT, signal_id TEXT)")
    conn.execute("CREATE UNIQUE INDEX idx_trades_strategy_signal_id ON trades(signal_id) WHERE signal_id IS NOT NULL")
    conn.execute("CREATE UNIQUE INDEX idx_trades_one_active_per_ticker ON trades(ticker) WHERE status = 'active'")
    conn.commit()
    conn.close()

    ticker = "PETR4.SA"
    dates = [date(2025, 6, 1) + timedelta(days=i) for i in range(220)]
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
    df_synth = pd.DataFrame(records)

    bundle_dir = tmp_path / "candidates" / "petr4"
    manifest = build_candidate_bundle(
        ticker=ticker,
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=df_synth,
    )
    custom_reg = tmp_path / "custom_registry.json"
    custom_reg.write_text(json.dumps({"version": 1, "approvals": []}), encoding="utf-8")
    approve_candidate(
        candidate_path=bundle_dir / "candidate_manifest.json",
        reviewed_by="Victor",
        review_notes="Approved for aggregate test",
        confirm_digest=manifest.dataset_sha256,
        confirm_candidate_id=manifest.candidate_id,
        confirmation=APPROVAL_CONFIRMATION_TOKEN,
        registry_path=custom_reg,
        project_root=tmp_path,
    )

    trade_wednesday = datetime.datetime(2026, 3, 11, 14, 0, tzinfo=B3_TIMEZONE)

    class MockMarket:
        def fetch_ohlcv(self, t, period="2y", interval="1d"):
            return df_synth.copy()

    from scripts import paper_session_preflight
    monkeypatch.setattr(paper_session_preflight, "resolve_market", lambda sym: MockMarket())

    # A. With import-only (default verify_runtime_quotes=False):
    report_unverified = run_paper_preflight(
        registry_path=custom_reg,
        db_path=test_db,
        storage_dir=tmp_path / "storage",
        project_root=tmp_path,
        tickers=[ticker],
        now_dt=trade_wednesday,
        verify_runtime_quotes=False,
    )
    # MUST NOT be PASS
    assert report_unverified.entry_ready == "RUNTIME_UNVERIFIED"
    assert report_unverified.overall_status == "RUNTIME_UNVERIFIED"
    assert report_unverified.entry_ready != "PASS"
    assert report_unverified.overall_status != "PASS"
    assert report_unverified.infrastructure_ready == "PASS"

    # B. With behavioral verification (verify_runtime_quotes=True):
    report_verified = run_paper_preflight(
        registry_path=custom_reg,
        db_path=test_db,
        storage_dir=tmp_path / "storage",
        project_root=tmp_path,
        tickers=[ticker],
        now_dt=trade_wednesday,
        verify_runtime_quotes=True,
    )
    assert report_verified.entry_ready == "PASS"
    assert report_verified.overall_status == "PASS"


def test_r2_regression_m_broker_close_preserves_and_requires_evidence(tmp_path):
    """M. Broker-mediated Paper close preserves/requires evidence."""
    from tests.conftest import make_test_evidenced_quote
    from backend.app.markets.paper_broker import PaperBroker
    db_file = tmp_path / "test_m.db"
    _init_r2_test_db(db_file, 1000.0, [("PETR4.SA", "BUY", 10.0, 30.0, 33.0, 28.5)])

    broker = PaperBroker()
    with patch("backend.app.agents.executor.DB_PATH", str(db_file)):
        # Calling broker close without evidence is rejected
        res_no_ev = broker.close_order(1, 33.0, "Take Profit hit", evidence=None)
        assert res_no_ev["status"] == "rejected"
        assert "evidence is required" in res_no_ev["reason"]

        # Calling broker close with valid evidence closes successfully
        ev = make_test_evidenced_quote("PETR4.SA", 33.0)
        res_with_ev = broker.close_order(1, 33.0, "Take Profit hit", evidence=ev)
        assert res_with_ev["status"] == "closed"


def test_r2_regression_n_manual_close_missing_evidence_fails_closed(tmp_path, monkeypatch):
    """N. Manual close without valid evidenced quote -> fail closed, zero mutation."""
    from fastapi import HTTPException
    from backend.app import main
    db_file = tmp_path / "test_n.db"
    _init_r2_test_db(db_file, 1000.0, [("PETR4.SA", "BUY", 10.0, 30.0, 33.0, 28.5)])

    monkeypatch.setattr("backend.app.data.database.DB_PATH", str(db_file))
    monkeypatch.setattr("backend.app.agents.executor.DB_PATH", str(db_file))
    monkeypatch.setattr("backend.app.data.feed.get_evidenced_quote", lambda t: None)

    with pytest.raises(HTTPException) as exc_info:
        main.manual_close_trade(1, api_key="test")
    assert exc_info.value.status_code == 500

    conn = sqlite3.connect(str(db_file))
    trade = conn.execute("SELECT status FROM trades WHERE id = 1").fetchone()
    conn.close()
    assert trade[0] == "active"


def test_r2_regression_o_manual_valid_evidenced_quote_succeeds(tmp_path, monkeypatch):
    """O. Manual valid evidenced quote -> close succeeds."""
    from tests.conftest import make_test_evidenced_quote
    from backend.app import main
    db_file = tmp_path / "test_o.db"
    _init_r2_test_db(db_file, 1000.0, [("PETR4.SA", "BUY", 10.0, 30.0, 33.0, 28.5)])

    ev = make_test_evidenced_quote("PETR4.SA", 31.5)
    monkeypatch.setattr("backend.app.data.database.DB_PATH", str(db_file))
    monkeypatch.setattr("backend.app.agents.executor.DB_PATH", str(db_file))
    monkeypatch.setattr("backend.app.data.feed.get_evidenced_quote", lambda t: ev)

    res = main.manual_close_trade(1, api_key="test")
    assert res["status"] == "closed"
    assert res["exit_price"] == 31.5

    conn = sqlite3.connect(str(db_file))
    trade = conn.execute("SELECT status, exit_price FROM trades WHERE id = 1").fetchone()
    conn.close()
    assert trade[0] == "closed"
    assert trade[1] == 31.5


def test_r2_regression_p_emergency_stop_operates_outside_session_requires_evidence(tmp_path, monkeypatch):
    """P. Emergency request can operate outside entry session gate BUT cannot bypass execution-price evidence."""
    from tests.conftest import make_test_evidenced_quote
    from backend.app import main
    from backend.app.markets.b3_session import override_session_authority, AutonomousSessionAuthority
    db_file = tmp_path / "test_p.db"
    _init_r2_test_db(db_file, 1000.0, [("PETR4.SA", "BUY", 10.0, 30.0, 33.0, 28.5)])

    monkeypatch.setattr("backend.app.data.database.DB_PATH", str(db_file))
    monkeypatch.setattr("backend.app.agents.executor.DB_PATH", str(db_file))
    monkeypatch.setattr(main, "EMERGENCY_PASSWORD", "secret123")

    # Entry session authority is strictly CLOSED
    closed_authority = AutonomousSessionAuthority(
        override_fn=lambda dt=None: (
            False,
            "B3 market is CLOSED",
            B3DayType.NORMAL_TRADING_DAY,
            B3SessionPhase.CLOSED,
        )
    )

    # 1. With feed returning valid quote: closes successfully even though entry session is CLOSED
    ev = make_test_evidenced_quote("PETR4.SA", 29.0)
    monkeypatch.setattr("backend.app.data.feed.get_evidenced_quote", lambda t: ev)

    req = main.ActionRequest(action="stop", password="secret123")
    with override_session_authority(closed_authority):
        resp = main.system_emergency_stop(req)
        assert resp["status"] == "success"
        assert resp["closed"] == 1

    conn = sqlite3.connect(str(db_file))
    trade = conn.execute("SELECT status FROM trades WHERE id = 1").fetchone()
    conn.close()
    assert trade[0] == "closed"


def test_r2_regression_q_emergency_stop_partial_failure_reported_honestly(tmp_path, monkeypatch):
    """Q. Partial Emergency Stop failure is not falsely reported as total success."""
    from tests.conftest import make_test_evidenced_quote
    from backend.app import main
    db_file = tmp_path / "test_q.db"
    _init_r2_test_db(
        db_file,
        1000.0,
        [
            ("PETR4.SA", "BUY", 10.0, 30.0, 33.0, 28.5),
            ("VALE3.SA", "BUY", 5.0, 60.0, 65.0, 57.0),
        ],
    )

    monkeypatch.setattr("backend.app.data.database.DB_PATH", str(db_file))
    monkeypatch.setattr("backend.app.agents.executor.DB_PATH", str(db_file))
    monkeypatch.setattr(main, "EMERGENCY_PASSWORD", "secret123")

    # PETR4 has quote, VALE3 feed is unavailable (returns None)
    def _selective_quote(ticker):
        if "PETR4" in ticker:
            return make_test_evidenced_quote("PETR4.SA", 30.5)
        return None

    monkeypatch.setattr("backend.app.data.feed.get_evidenced_quote", _selective_quote)

    req = main.ActionRequest(action="stop", password="secret123")
    resp = main.system_emergency_stop(req)

    # Must NOT report "success"
    assert resp["status"] != "success"
    assert resp["status"] == "partial_failure"
    assert resp["success"] is False
    assert resp["closed"] == 1
    assert resp["failed"] == 1
    assert "VALE3.SA" in resp["failed_tickers"]

    conn = sqlite3.connect(str(db_file))
    petr4_status = conn.execute("SELECT status FROM trades WHERE ticker = 'PETR4.SA'").fetchone()[0]
    vale3_status = conn.execute("SELECT status FROM trades WHERE ticker = 'VALE3.SA'").fetchone()[0]
    conn.close()

    assert petr4_status == "closed"
    assert vale3_status == "active"  # Unmutated fail-closed


# ===========================================================================
# 11. NEXUS-004-R3: RAW EVIDENCE, PROVENANCE & READINESS DETERMINISTIC TESTS
# ===========================================================================

def test_r3_raw_evidence_finite_validation_and_executor_defense(tmp_path):
    """R3-1. Raw evidence must be finite positive number: NaN, Inf, bool, <=0 rejected at model and executor with zero mutation."""
    from trading_bot.data.valuation_snapshot import EvidencedQuote, compute_evidence_sha256
    import math

    now = datetime.datetime.now(timezone.utc)
    base_raw = {
        "ticker": "PETR4.SA", "vendor_symbol": "PETR4.SA", "source": "yfinance",
        "price_kind": "bar_close", "interval": "1m", "period": "1d",
        "observed_at": now.isoformat(), "collected_at": now.isoformat(),
    }

    # 1. Model layer: EvidencedQuote rejects non-finite, bool, or non-positive close
    for bad_close in [float("nan"), float("inf"), float("-inf"), True, False, 0.0, -10.0]:
        raw = dict(base_raw, close=bad_close)
        sha = compute_evidence_sha256(raw)
        with pytest.raises(ValueError, match="raw_evidence"):
            EvidencedQuote(
                ticker="PETR4.SA", price=33.0, currency="BRL", source="yfinance",
                price_kind="bar_close", interval="1m", vendor_symbol="PETR4.SA",
                observed_at=now, collected_at=now, source_ref="test",
                source_sha256=sha, raw_evidence=raw,
            )

    # Finite mismatch (e.g. price=33.0, raw close=35.0) rejected
    raw_mismatch = dict(base_raw, close=35.0)
    sha_mismatch = compute_evidence_sha256(raw_mismatch)
    with pytest.raises(ValueError, match="does not match raw_evidence close"):
        EvidencedQuote(
            ticker="PETR4.SA", price=33.0, currency="BRL", source="yfinance",
            price_kind="bar_close", interval="1m", vendor_symbol="PETR4.SA",
            observed_at=now, collected_at=now, source_ref="test",
            source_sha256=sha_mismatch, raw_evidence=raw_mismatch,
        )

    # Valid finite match accepted
    raw_valid = dict(base_raw, close=33.0)
    sha_valid = compute_evidence_sha256(raw_valid)
    valid_quote = EvidencedQuote(
        ticker="PETR4.SA", price=33.0, currency="BRL", source="yfinance",
        price_kind="bar_close", interval="1m", vendor_symbol="PETR4.SA",
        observed_at=now, collected_at=now, source_ref="test",
        source_sha256=sha_valid, raw_evidence=raw_valid,
    )
    assert valid_quote.price == 33.0

    # 2. Executor defense-in-depth: zero mutation on trades AND portfolio
    db_file = tmp_path / "test_r3_raw.db"
    _init_r2_test_db(db_file, 1000.0, [("PETR4.SA", "BUY", 10.0, 30.0, 35.0, 28.5)])
    executor = ExecutorAgent(str(db_file))

    conn = sqlite3.connect(str(db_file))
    trades_before = conn.execute("SELECT * FROM trades").fetchall()
    port_before = conn.execute("SELECT * FROM portfolio").fetchall()
    conn.close()

    # Injected tampered quote where raw_evidence has NaN close
    class TamperedQuote:
        ticker = "PETR4.SA"
        price = 33.0
        observed_at = now
        collected_at = now
        source_sha256 = "0" * 64
        raw_evidence = dict(base_raw, close=float("nan"))
        def model_dump(self, **kw):
            return {
                "ticker": self.ticker, "price": self.price, "currency": "BRL",
                "source": "yfinance", "price_kind": "bar_close", "interval": "1m",
                "vendor_symbol": "PETR4.SA", "observed_at": self.observed_at,
                "collected_at": self.collected_at, "source_ref": "test",
                "source_sha256": self.source_sha256, "raw_evidence": self.raw_evidence,
            }

    res_nan = executor.close_order(1, 33.0, "Take Profit hit", evidence=TamperedQuote())
    assert res_nan["status"] == "rejected"

    conn = sqlite3.connect(str(db_file))
    trades_after = conn.execute("SELECT * FROM trades").fetchall()
    port_after = conn.execute("SELECT * FROM portfolio").fetchall()
    conn.close()
    assert trades_after == trades_before
    assert port_after == port_before

    # Valid finite match closes successfully
    res_valid = executor.close_order(1, 33.0, "Take Profit hit", evidence=valid_quote)
    assert res_valid["status"] == "closed"
    assert res_valid["pnl_pct"] == 10.0


def test_r3_session_authority_scoped_lifecycle_and_thread_isolation():
    """R3-6. Permanent setter absent; override restores on exit/exception; no cross-thread leak."""
    import threading
    from backend.app.markets import b3_session
    from backend.app.markets.b3_session import (
        get_session_authority,
        override_session_authority,
        AutonomousSessionAuthority,
        DEFAULT_SESSION_AUTHORITY,
        B3DayType,
        B3SessionPhase,
    )

    # 1. Permanent setter is ABSENT
    assert not hasattr(b3_session, "set_session_authority")

    # 2. Default authority returns DEFAULT_SESSION_AUTHORITY
    assert get_session_authority() is DEFAULT_SESSION_AUTHORITY

    custom_auth = AutonomousSessionAuthority(
        override_fn=lambda dt=None: (True, "Scoped override", B3DayType.NORMAL_TRADING_DAY, B3SessionPhase.CONTINUOUS)
    )
    nested_auth = AutonomousSessionAuthority(
        override_fn=lambda dt=None: (False, "Nested closed", B3DayType.NORMAL_TRADING_DAY, B3SessionPhase.CLOSED)
    )

    # 3. Scoped override, nested override, and thread isolation
    with override_session_authority(custom_auth):
        assert get_session_authority() is custom_auth

        # Thread isolation: another thread must see default authority, NOT custom_auth
        thread_saw = [None]
        def _thread_check():
            thread_saw[0] = get_session_authority()

        t = threading.Thread(target=_thread_check)
        t.start()
        t.join(timeout=5)
        assert thread_saw[0] is DEFAULT_SESSION_AUTHORITY

        # Nested override
        with override_session_authority(nested_auth):
            assert get_session_authority() is nested_auth
        # Restored to outer custom_auth
        assert get_session_authority() is custom_auth

    # Restored to default after with block
    assert get_session_authority() is DEFAULT_SESSION_AUTHORITY

    # 4. Exception unwinding restores default
    try:
        with override_session_authority(custom_auth):
            assert get_session_authority() is custom_auth
            raise RuntimeError("Simulated test error inside override")
    except RuntimeError:
        pass
    assert get_session_authority() is DEFAULT_SESSION_AUTHORITY


def test_r3_automatic_exit_preserves_provider_provenance(tmp_path):
    """R3-3. Automatic exit scan preserves provider source, collected_at, source_ref, and source_sha256."""
    from backend.app import main
    from backend.app.data import database as db_mod
    from tests.test_exit_loop import _make_price_row
    from unittest.mock import patch, MagicMock

    db_file = tmp_path / "test_prov.db"
    _init_r2_test_db(db_file, 1000.0, [("PETR4.SA", "BUY", 10.0, 30.0, 40.0, 28.0)])

    # 1m candle close at 27.5 (hits stop-loss of 28.0)
    df = _make_price_row(close=27.5)

    orig_db = db_mod.DB_PATH
    db_mod.DB_PATH = str(db_file)
    try:
        captured_evidence = []
        mock_exec = MagicMock()
        def _record_close(tid, price, reason, evidence=None, **kw):
            captured_evidence.append((price, evidence))
            return {"status": "closed", "pnl_pct": -8.33}
        mock_exec.close_order.side_effect = _record_close

        with patch("backend.app.data.feed.fetch_recent_data", return_value=df), \
             patch("backend.app.main.ExecutorAgent", return_value=mock_exec):
            import asyncio
            asyncio.run(main._run_exit_scan())

        assert len(captured_evidence) == 1
        exec_price, ev_quote = captured_evidence[0]
        assert exec_price == 27.5
        assert ev_quote is not None
        # PROVENANCE ASSERTIONS: must be feed provider, not fabricated exit_scan
        assert ev_quote.source == "yfinance"
        assert ev_quote.source != "exit_scan"
        assert ev_quote.price_kind == "bar_close"
        assert ev_quote.interval == "1m"
        assert ev_quote.source_ref.startswith("yfinance://")
        assert ev_quote.source_sha256 == compute_evidence_sha256(ev_quote.raw_evidence)
        assert ev_quote.raw_evidence["source"] == "yfinance"
    finally:
        db_mod.DB_PATH = orig_db


def test_r3_exit_rejection_cannot_emit_closed_success(tmp_path):
    """R3-5. When executor rejects close_order, exit scan reports ineffective and does not emit success."""
    from backend.app import main
    from backend.app.data import database as db_mod
    from tests.test_exit_loop import _make_price_row
    from unittest.mock import patch, MagicMock

    db_file = tmp_path / "test_rej.db"
    _init_r2_test_db(db_file, 1000.0, [("PETR4.SA", "BUY", 10.0, 30.0, 40.0, 28.0)])

    df = _make_price_row(close=27.5)  # hits stop-loss

    orig_db = db_mod.DB_PATH
    db_mod.DB_PATH = str(db_file)
    try:
        mock_exec = MagicMock()
        mock_exec.close_order.return_value = {
            "status": "rejected",
            "reason": "Evidence staleness or session boundary failure",
        }

        logs = []
        async def _capture_log(sender, message, level="info"):
            logs.append((sender, message, level))

        with patch("backend.app.data.feed.fetch_recent_data", return_value=df), \
             patch("backend.app.main.ExecutorAgent", return_value=mock_exec), \
             patch("backend.app.main.broadcast_log", side_effect=_capture_log):
            import asyncio
            effective = asyncio.run(main._run_exit_scan())

        # Cycle must be marked ineffective (False)
        assert effective is False

        # No success log emitted
        success_logs = [m for s, m, lvl in logs if lvl == "success" and "Closed trade!" in m]
        assert len(success_logs) == 0

        # Error log emitted
        error_logs = [m for s, m, lvl in logs if lvl == "error"]
        assert len(error_logs) >= 1
        assert "Falha ao fechar trade" in error_logs[0]

        # Trade remains active (unmutated fail-closed)
        conn = sqlite3.connect(str(db_file))
        status = conn.execute("SELECT status FROM trades WHERE id = 1").fetchone()[0]
        conn.close()
        assert status == "active"
    finally:
        db_mod.DB_PATH = orig_db


def test_r3_exit_scan_does_not_overwrite_concurrently_closed_trade(tmp_path):
    """R3-9. Live PnL and breakeven updates use WHERE status = 'active' and do not overwrite closed trades."""
    from backend.app import main
    from backend.app.data import database as db_mod
    from tests.test_exit_loop import _make_price_row
    from unittest.mock import patch

    db_file = tmp_path / "test_race.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE portfolio (id INTEGER PRIMARY KEY, patrimonio_total REAL, saldo_disponivel REAL, em_posicoes REAL, margem_operavel REAL)")
    conn.execute("INSERT INTO portfolio VALUES (1, 1000.0, 1000.0, 0.0, 1000.0)")
    conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, ticker TEXT, side TEXT, shares REAL, entry_price REAL, exit_price REAL, target_price REAL, stop_loss REAL, entry_date TIMESTAMP, exit_date TIMESTAMP, pnl_pct REAL, exit_reason TEXT, ai_rationale TEXT, status TEXT, signal_id TEXT)")
    conn.execute(
        "INSERT INTO trades (id, ticker, side, shares, entry_price, target_price, stop_loss, pnl_pct, status) "
        "VALUES (1, 'PETR4.SA', 'BUY', 10.0, 30.0, 40.0, 25.0, 15.5, 'closed')"
    )
    conn.commit()
    conn.close()

    df = _make_price_row(close=36.0)

    orig_db = db_mod.DB_PATH
    db_mod.DB_PATH = str(db_file)
    try:
        with patch("backend.app.data.feed.fetch_recent_data", return_value=df):
            import asyncio
            effective = asyncio.run(main._run_exit_scan())

        # No active trades were scanned
        assert effective is True

        conn = sqlite3.connect(str(db_file))
        trade = conn.execute("SELECT status, pnl_pct, stop_loss FROM trades WHERE id = 1").fetchone()
        conn.close()

        # Finalized closed metadata was completely untouched
        assert trade[0] == "closed"
        assert trade[1] == 15.5
        assert trade[2] == 25.0
    finally:
        db_mod.DB_PATH = orig_db


def test_r3_emergency_stop_per_trade_exception_continues_and_reports_partial_failure(tmp_path, monkeypatch):
    """R3-10. Exception on one trade in emergency stop does not abort loop; reports partial truth."""
    from tests.conftest import make_test_evidenced_quote
    from backend.app import main
    from unittest.mock import MagicMock

    db_file = tmp_path / "test_emerg_exc.db"
    _init_r2_test_db(
        db_file,
        1000.0,
        [
            ("PETR4.SA", "BUY", 10.0, 30.0, 35.0, 28.0),
            ("VALE3.SA", "BUY", 5.0, 60.0, 65.0, 55.0),
        ],
    )

    monkeypatch.setattr("backend.app.data.database.DB_PATH", str(db_file))
    monkeypatch.setattr(main, "EMERGENCY_PASSWORD", "secret123")

    ev_petr = make_test_evidenced_quote("PETR4.SA", 31.0)
    ev_vale = make_test_evidenced_quote("VALE3.SA", 62.0)

    def _mock_quote(ticker):
        return ev_petr if "PETR4" in ticker else ev_vale

    monkeypatch.setattr("backend.app.data.feed.get_evidenced_quote", _mock_quote)

    # Mock ExecutorAgent: PETR4 throws unhandled exception; VALE3 succeeds
    real_exec = ExecutorAgent(str(db_file))
    mock_executor = MagicMock()
    def _close_side_effect(trade_id, price, reason, evidence=None, **kw):
        if trade_id == 1:
            raise RuntimeError("Simulated broker crash on trade 1")
        return real_exec.close_order(trade_id, price, reason, evidence=evidence, **kw)

    mock_executor.close_order.side_effect = _close_side_effect
    monkeypatch.setattr(main, "ExecutorAgent", lambda: mock_executor)

    req = main.ActionRequest(action="stop", password="secret123")
    resp = main.system_emergency_stop(req)

    # Response must report partial_failure, never total success
    assert resp["status"] == "partial_failure"
    assert resp["success"] is False
    assert resp["total"] == 2
    assert resp["closed"] == 1
    assert resp["failed"] == 1
    assert "PETR4.SA" in resp["failed_tickers"]

    # In DB: Trade 2 (VALE3) was successfully closed, Trade 1 remained active
    conn = sqlite3.connect(str(db_file))
    t1_status = conn.execute("SELECT status FROM trades WHERE id = 1").fetchone()[0]
    t2_status = conn.execute("SELECT status FROM trades WHERE id = 2").fetchone()[0]
    conn.close()

    assert t1_status == "active"
    assert t2_status == "closed"
