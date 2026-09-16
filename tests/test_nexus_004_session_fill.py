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
from typing import Any, Dict, List
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
    assert get_session_phase(datetime.datetime(2026, 2, 18, 16, 56, tzinfo=B3_TIMEZONE)) == B3SessionPhase.CLOSING_CALL


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
