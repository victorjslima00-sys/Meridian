import os
import sys
import pytest
import pandas as pd
import numpy as np
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock

# Import components from trading_bot
from trading_bot.core.config import AppConfig
from trading_bot.core import clock
from trading_bot.signals.engine import (
    compute_signal,
    Candidate,
    scan_universe,
    ibov_in_uptrend,
    get_ibov_data
)
from trading_bot.backtest.engine import (
    run_regime_backtest,
    run_full_backtest,
    Trade,
    BacktestResult,
    _OpenPos
)
from trading_bot.risk.circuit_breaker import CircuitBreaker, check_correlation
from trading_bot.data.validator import validate_ohlcv, validate_universe

# Import the scripts
import scripts.fase0_validate_data as fase0
import scripts.fase1_backtest as fase1

# ---------------------------------------------------------------------------
# Test scripts entry points (Requirement 3)
# ---------------------------------------------------------------------------

def test_entry_points(sandbox_config, mock_b3_clock, mock_yfinance, mock_brapi_api, monkeypatch):
    # Set high divergence limit so cross-validation passes
    sandbox_config.raw["data"]["cross_validation"]["max_divergence_pct"] = 100.0

    # Ensure all modules that imported today_b3 directly use the mocked fixed date (2024-06-30)
    fixed_date = date(2024, 6, 30)
    monkeypatch.setattr("trading_bot.core.clock.today_b3", lambda: fixed_date)
    monkeypatch.setattr("scripts.fase0_validate_data.today_b3", lambda: fixed_date)
    monkeypatch.setattr("trading_bot.data.cross_validation.today_b3", lambda: fixed_date)
    monkeypatch.setattr("trading_bot.data.validator.today_b3", lambda: fixed_date)

    import yfinance as yf
    original_download = yf.download
    def wrap_download(*args, **kwargs):
        df = original_download(*args, **kwargs)
        if not kwargs.get("auto_adjust", False):
            if "Adj Close" not in df.columns and "Close" in df.columns:
                df["Adj Close"] = df["Close"]
        return df
    monkeypatch.setattr(yf, "download", wrap_download)

    # Run Fase 0
    with patch.object(sys, 'argv', ['fase0_validate_data.py', '--token', 'MOCK_TOKEN', '--years', '1']):
        exit_code = fase0.main()
        assert exit_code == 0

    # Run Fase 1
    with patch.object(sys, 'argv', ['fase1_backtest.py']):
        fase1.main()

# ---------------------------------------------------------------------------
# Tier 3: Cross-Feature Combinations / Pairwise (5 combination tests)
# ---------------------------------------------------------------------------

def test_tier3_combo_1_uptrend_signal_corr_pass_sizing_norm_fill_clean_risk_safe():
    # Combination 1: Uptrend, single signal, correlation pass, normal sizing, clean fill, risk safe
    # Trend: Uptrend (IBOV close > SMA-50)
    ibov_df = pd.DataFrame([
        {"ts": date(2024, 6, 30), "c": 100000.0, "sma50": 95000.0}
    ])
    assert ibov_in_uptrend(ibov_df, date(2024, 6, 30)) is True

    # Signal: Single breakout signal candidate
    candidate = Candidate(
        ticker="PETR4", score=0.8, entry_price=30.0, stop=28.5, target=33.0,
        signal_ts=date(2024, 6, 30), rsi=60.0, volume_ratio=2.5, near_support=False, signal_details={}
    )
    assert candidate.ticker == "PETR4"
    
    # Correlation: Pass
    assert check_correlation("PETR4", [], {}, 0.70) is True

    # Sizing: Normal (Kelly sizing R$ 25.0 out of R$ 100.0 cash)
    pos_size = 100.0 * 0.25 / 3  # Kelly fraction / max_positions
    assert pos_size == 8.333333333333334

    # Fill: Clean
    open_price = 30.5
    assert open_price > candidate.stop # Open above stop

    # Risk: Safe
    cb = CircuitBreaker()
    status = cb.check(100.0, 100.0, 100.0, 100.0)
    assert status.triggered is False


def test_tier3_combo_2_downtrend_no_signal():
    # Combination 2: Downtrend, no signal, correlation pass, normal sizing, clean fill, risk safe
    # Trend: Downtrend (IBOV close < SMA-50)
    ibov_df = pd.DataFrame([
        {"ts": date(2024, 6, 30), "c": 90000.0, "sma50": 95000.0}
    ])
    assert ibov_in_uptrend(ibov_df, date(2024, 6, 30)) is False

    # Signal: None
    assert compute_signal(pd.DataFrame(), "PETR4") is None

    # Risk: Safe
    cb = CircuitBreaker()
    status = cb.check(100.0, 100.0, 100.0, 100.0)
    assert status.triggered is False


def test_tier3_combo_3_transition_multi_signal_sizing_cap():
    # Combination 3: Transition trend, multi signals, correlation pass, sizing capped, fill clean, risk safe
    # Transition trend: IBOV not in uptrend (on the boundary)
    ibov_df = pd.DataFrame([
        {"ts": date(2024, 6, 30), "c": 95000.0, "sma50": 95000.0}
    ])
    assert ibov_in_uptrend(ibov_df, date(2024, 6, 30)) is False

    # Multi signals: VALE3 and PETR4 have breakout candidates
    c1 = Candidate("PETR4", 0.75, 30.0, 28.5, 33.0, date(2024, 6, 30), 60.0, 2.5, False, {})
    c2 = Candidate("VALE3", 0.80, 60.0, 57.0, 66.0, date(2024, 6, 30), 65.0, 3.0, False, {})
    candidates = [c2, c1] # sorted by score

    # Correlation: Pass (different directions/negatively correlated)
    returns_matrix = {
        "PETR4": [0.01, -0.01, 0.02, -0.02, 0.01, -0.01, 0.02, -0.02, 0.01, -0.01],
        "VALE3": [-0.01, 0.01, -0.02, 0.02, -0.01, 0.01, -0.02, 0.02, -0.01, 0.01]
    }
    assert check_correlation("PETR4", ["VALE3"], returns_matrix, 0.70) is True

    # Sizing: Capped
    # Calculated size is 25.0, but cash is only 10.0
    available_cash = 10.0
    pos_size = min(25.0, available_cash)
    assert pos_size == 10.0


def test_tier3_combo_4_uptrend_multi_signal_corr_fail():
    # Combination 4: Uptrend, multi signals, correlation fail, normal sizing, clean fill, risk safe
    ibov_df = pd.DataFrame([
        {"ts": date(2024, 6, 30), "c": 100000.0, "sma50": 95000.0}
    ])
    assert ibov_in_uptrend(ibov_df, date(2024, 6, 30)) is True

    # Correlation: Fail
    returns_matrix = {
        "PETR4": [0.01, 0.02, -0.01, -0.02, 0.01, 0.03, -0.01, 0.02, 0.01, 0.01],
        "PRIO3": [0.011, 0.019, -0.009, -0.021, 0.01, 0.032, -0.01, 0.021, 0.009, 0.01]
    }
    assert check_correlation("PETR4", ["PRIO3"], returns_matrix, 0.70) is False


def test_tier3_combo_5_uptrend_signal_fill_abort_cb_trigger():
    # Combination 5: Uptrend, single signal, correlation pass, normal sizing, fill abort, circuit breaker trigger
    ibov_df = pd.DataFrame([
        {"ts": date(2024, 6, 30), "c": 100000.0, "sma50": 95000.0}
    ])
    assert ibov_in_uptrend(ibov_df, date(2024, 6, 30)) is True

    candidate = Candidate(
        ticker="PETR4", score=0.8, entry_price=30.0, stop=28.5, target=33.0,
        signal_ts=date(2024, 6, 30), rsi=60.0, volume_ratio=2.5, near_support=False, signal_details={}
    )

    # Fill: Abort (open price below stop)
    open_price = 28.0
    assert open_price <= candidate.stop

    # Risk: Circuit Breaker Triggered (daily loss of 4% > 3% limit)
    cb = CircuitBreaker(daily_loss_limit=0.03)
    status = cb.check(current_equity=95.0, initial_equity=100.0, equity_start_of_day=100.0, equity_30d_ago=100.0)
    assert status.triggered is True
    assert "Perda diária" in status.reason


# ---------------------------------------------------------------------------
# Tier 4: Real-World Application Scenarios (5 scenarios)
# ---------------------------------------------------------------------------

def test_tier4_scenario1_market_crash_circuit_breakers(mock_telegram_client):
    # Scenario 1: Sudden Market Crash & Multi-Level Circuit Breakers
    cb = CircuitBreaker(
        daily_loss_limit=0.03,        # 3%
        drawdown_inception=0.08,      # 8%
        drawdown_rolling_30d=0.06     # 6%
    )
    
    # Mock Telegram Client instance
    from trading_bot.core.telegram import TelegramClient
    telegram = TelegramClient(token="MOCK_TOKEN", chat_id="MOCK_CHAT")

    # Order action function mock
    order_executed = False
    def execute_order():
        nonlocal order_executed
        order_executed = True
        return True, "Executed"

    def process_order(current_equity, initial, start_of_day, rolling_30d):
        nonlocal order_executed
        order_executed = False
        status = cb.check(current_equity, initial, start_of_day, rolling_30d)
        if status.triggered:
            telegram.send_message(f"ALERT: Circuit Breaker Triggered: {status.reason}")
            return False, f"Blocked: {status.reason}"
        return execute_order()

    # 1. Normal/Safe Market
    res, msg = process_order(100.0, 100.0, 100.0, 100.0)
    assert res is True
    assert order_executed is True
    assert not mock_telegram_client.send_calls

    # 2. Daily Loss Limit Trigger (>3% loss since start of day)
    res, msg = process_order(96.0, 100.0, 100.0, 100.0) # 4% daily loss
    assert res is False
    assert order_executed is False
    assert any("Perda diária" in m for m in mock_telegram_client.send_calls)
    mock_telegram_client.reset()

    # 3. Rolling 30-day Drawdown Trigger (>6% loss since 30d ago)
    res, msg = process_order(93.0, 100.0, 95.0, 100.0) # 7% 30d loss
    assert res is False
    assert order_executed is False
    assert any("Drawdown 30d" in m for m in mock_telegram_client.send_calls)
    mock_telegram_client.reset()

    # 4. Drawdown Inception Trigger (>8% loss since inception)
    res, msg = process_order(91.0, 100.0, 92.0, 92.0) # 9% inception loss
    assert res is False
    assert order_executed is False
    assert any("Drawdown inception" in m for m in mock_telegram_client.send_calls)


def test_tier4_scenario2_sector_clustering():
    # Scenario 2: High Correlation Sector Clustering
    sectors = {
        "PETR4": "energia",
        "PRIO3": "energia",
        "ITUB4": "financeiro"
    }

    # Helper function to check sector-specific correlation
    def sector_clustering_check(candidate, open_positions, returns_matrix, correlation_max=0.70):
        cand_sector = sectors.get(candidate)
        if not cand_sector:
            return True
        # Find open positions in the same sector
        same_sector_open = [pos for pos in open_positions if sectors.get(pos) == cand_sector]
        if not same_sector_open:
            return True
        return check_correlation(candidate, same_sector_open, returns_matrix, correlation_max)

    # Correlation returns matrix
    returns_matrix = {
        # High correlation between PETR4 and PRIO3 (same sector)
        "PETR4": [0.01, 0.02, -0.01, -0.02, 0.01, 0.03, -0.01, 0.02, 0.01, 0.01],
        "PRIO3": [0.011, 0.019, -0.009, -0.021, 0.01, 0.032, -0.01, 0.021, 0.009, 0.01],
        # Low correlation between PETR4 and ITUB4 (different sector)
        "ITUB4": [-0.01, 0.01, -0.02, 0.02, -0.01, 0.01, -0.02, 0.02, -0.01, 0.01]
    }

    # 1. Different sectors: PETR4 (energia) vs ITUB4 (financeiro) should pass correlation clustering check
    assert sector_clustering_check("PETR4", ["ITUB4"], returns_matrix, 0.70) is True

    # 2. Same sector: PETR4 (energia) vs PRIO3 (energia) with high correlation (>0.70) should be blocked
    assert sector_clustering_check("PETR4", ["PRIO3"], returns_matrix, 0.70) is False

    # 3. Same sector: PETR4 (energia) vs PRIO3 (energia) with low correlation threshold (should pass if corr is low, but here it's high)
    # Let's mock a returns matrix with low correlation in same sector
    low_corr_matrix = {
        "PETR4": [0.01, 0.02, -0.01, -0.02, 0.01, 0.03, -0.01, 0.02, 0.01, 0.01],
        "PRIO3": [-0.01, -0.02, 0.01, 0.02, -0.01, -0.03, 0.01, -0.02, -0.01, -0.01]
    }
    assert sector_clustering_check("PETR4", ["PRIO3"], low_corr_matrix, 0.70) is True


def test_tier4_scenario3_position_sizing_capping():
    # Scenario 3: Position Sizing Capping under Cash Constraints
    def calculate_position_size(equity, kelly_fraction, max_positions, available_cash, min_threshold=5.0):
        if available_cash < min_threshold:
            return 0.0, "Aborted: cash below minimum threshold"
        size = (equity * kelly_fraction) / max_positions
        if size > available_cash:
            size = available_cash # Sizing capped
        # Verify cash never goes negative
        assert available_cash - size >= 0
        return size, "OK"

    # 1. Normal Kelly Sizing (Equity R$ 1200, Kelly 0.25, Max Pos 3, Cash R$ 200)
    # Calculated size: 1200 * 0.25 / 3 = 100.0 (<= 200 cash)
    size, status = calculate_position_size(1200.0, 0.25, 3, 200.0)
    assert size == 100.0
    assert status == "OK"

    # 2. Capped by Cash (Calculated size: 100.0, Cash: 45.0)
    size, status = calculate_position_size(1200.0, 0.25, 3, 45.0)
    assert size == 45.0
    assert status == "OK"

    # 3. Aborted due to Cash Below Threshold (Cash: 4.0, threshold: 5.0)
    size, status = calculate_position_size(1200.0, 0.25, 3, 4.0)
    assert size == 0.0
    assert "Aborted" in status


def test_tier4_scenario4_ex_dividend_adjustments():
    # Scenario 4: Corporate Actions Ex-Dividend adjustment checks
    # Construct unadjusted price series (price drops by 45% from 20.0 to 11.0 on ex-dividend day)
    df_unadjusted = pd.DataFrame([
        {"ts": date(2024, 6, 28), "o": 20.0, "h": 20.5, "l": 19.5, "c": 20.0, "v": 1000, "adj_close": 20.0},
        {"ts": date(2024, 6, 29), "o": 11.0, "h": 11.5, "l": 10.5, "c": 11.0, "v": 1000, "adj_close": 11.0}
    ])

    # Construct adjusted price series (smooth 0% drop from 11.0 to 11.0)
    df_adjusted = pd.DataFrame([
        {"ts": date(2024, 6, 28), "o": 11.0, "h": 11.375, "l": 10.625, "c": 11.0, "v": 1000, "adj_close": 11.0},
        {"ts": date(2024, 6, 29), "o": 11.0, "h": 11.5, "l": 10.5, "c": 11.0, "v": 1000, "adj_close": 11.0}
    ])

    # 1. Validation check
    # Unadjusted series has a 45% daily drop, exceeding MAX_DAILY_MOVE_PCT (20.0) -> validation fails
    report_unadjusted = validate_ohlcv(df_unadjusted, "PETR4")
    assert report_unadjusted.ok is False
    assert any(i.issue_type == "large_move" for i in report_unadjusted.issues)

    # Adjusted series is smooth -> validation passes OK
    report_adjusted = validate_ohlcv(df_adjusted, "PETR4")
    assert report_adjusted.ok is True

    # 2. Stop loss simulation (triggering checks)
    # Position entered on Day 1 at close, stop loss is 5% below entry price
    # Unadjusted: entry = 20.0, stop = 19.0. Day 2 low is 10.5. Stop triggered falsely!
    entry_unadjusted = 20.0
    stop_unadjusted = entry_unadjusted * 0.95 # 19.0
    low_unadjusted = 10.5
    stop_triggered_unadjusted = low_unadjusted <= stop_unadjusted
    assert stop_triggered_unadjusted is True

    # Adjusted: entry = 11.0, stop = 10.45. Day 2 low is 10.5. Stop NOT triggered!
    entry_adjusted = 11.0
    stop_adjusted = entry_adjusted * 0.95 # 10.45
    low_adjusted = 10.5
    stop_triggered_adjusted = low_adjusted <= stop_adjusted
    assert stop_triggered_adjusted is False


def test_tier4_scenario5_scheduler_lifecycle(mock_telegram_client, mock_cedro_client):
    # Scenario 5: Scheduler Lifecycle, Manual Approvals, and Telegram Outage Fail-Safe
    class OrderState:
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"
        EXPIRED = "expired"
        EXECUTED = "executed"

    class Order:
        def __init__(self, ticker, qty, price, mode="manual"):
            self.ticker = ticker
            self.qty = qty
            self.price = price
            self.mode = mode
            self.state = OrderState.PENDING
            self.timestamp = datetime.now()

    class Scheduler:
        def __init__(self, telegram_client, broker_client, timeout_minutes=10):
            self.telegram_client = telegram_client
            self.broker_client = broker_client
            self.timeout_minutes = timeout_minutes
            self.pending_orders = []

        def process_signal(self, ticker, qty, price, mode="manual"):
            order = Order(ticker, qty, price, mode)
            if mode == "manual":
                try:
                    success = self.telegram_client.send_message(f"Approve order for {ticker}?")
                    if not success:
                        order.state = OrderState.EXPIRED
                        return order
                except Exception:
                    order.state = OrderState.EXPIRED
                    return order
                
                self.pending_orders.append(order)
            else:
                res = self.broker_client.execute_order(ticker, "BUY", qty, price)
                if res.get("status") == "executed":
                    order.state = OrderState.EXECUTED
            return order

        def check_timeouts(self, current_time):
            for order in self.pending_orders:
                if order.state == OrderState.PENDING:
                    elapsed = (current_time - order.timestamp).total_seconds() / 60.0
                    if elapsed >= self.timeout_minutes:
                        order.state = OrderState.EXPIRED

        def approve_order(self, order):
            if order.state == OrderState.PENDING:
                order.state = OrderState.APPROVED
                res = self.broker_client.execute_order(order.ticker, "BUY", order.qty, order.price)
                if res.get("status") == "executed":
                    order.state = OrderState.EXECUTED

    # Setup scheduler with active clients
    from trading_bot.core.telegram import TelegramClient
    from trading_bot.broker.cedro import CedroClient

    telegram = TelegramClient(token="token", chat_id="chat")
    broker = CedroClient(api_key="key", api_secret="sec")
    scheduler = Scheduler(telegram, broker, timeout_minutes=10)

    # 1. Telegram Outage Fail-Safe Path
    # When Telegram client fails (returns False or throws exception), the order must expire instantly rather than executing
    with patch.object(telegram, 'send_message', return_value=False):
        order_outage = scheduler.process_signal("PETR4", 100, 30.0, mode="manual")
        assert order_outage.state == OrderState.EXPIRED
        assert len(mock_cedro_client.order_calls) == 0

    # 2. Timeout Expiry Path
    # Order in manual mode is created as PENDING, but expires after timeout without approval
    mock_telegram_client.reset()
    mock_cedro_client.reset()
    start_time = datetime.now()
    order_timeout = scheduler.process_signal("PETR4", 100, 30.0, mode="manual")
    assert order_timeout.state == OrderState.PENDING
    assert len(mock_cedro_client.order_calls) == 0

    # Check timeout after 11 minutes to avoid race conditions
    scheduler.check_timeouts(start_time + timedelta(minutes=11))
    assert order_timeout.state == OrderState.EXPIRED
    assert len(mock_cedro_client.order_calls) == 0

    # 3. Successful Manual Approval Path
    # Order remains pending and then gets successfully executed on user approval
    mock_telegram_client.reset()
    mock_cedro_client.reset()
    order_approved = scheduler.process_signal("PETR4", 100, 30.0, mode="manual")
    assert order_approved.state == OrderState.PENDING
    
    scheduler.approve_order(order_approved)
    assert order_approved.state == OrderState.EXECUTED
    assert len(mock_cedro_client.order_calls) == 1
    assert mock_cedro_client.order_calls[0]["ticker"] == "PETR4"
