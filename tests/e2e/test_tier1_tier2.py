import os
import sys
import json
import sqlite3
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest
import requests

from trading_bot.core.config import AppConfig
from trading_bot.core import clock
from trading_bot.data.ingestion import fetch_yfinance, fetch_brapi, _normalize
from trading_bot.data.storage import initialize_db, save_ohlcv, load_ohlcv, get_delta_start
from trading_bot.data.validator import validate_ohlcv
from trading_bot.data.cross_validation import (
    validate_ticker_current_quote,
    validate_ticker_adjustment_consistency,
    run_cross_validation
)
from trading_bot.backtest.engine import run_regime_backtest, BacktestResult, Trade
from trading_bot.signals.engine import compute_signal
from trading_bot.backtest.metrics import (
    compute_aggregate_metrics,
    _trade_sharpe,
    _max_drawdown,
    _profit_factor,
    _stress_test_gap
)

class MockResponse:
    def __init__(self, json_data, status_code=200):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status_code != 200:
            raise requests.HTTPError(f"Mock HTTP Error {self.status_code}")

def _generate_synthetic_data(n_rows=250, trend="up", breakout_idx=None):
    start_date = date(2024, 1, 1)
    dates = [start_date + timedelta(days=i) for i in range(n_rows)]
    
    if trend == "up":
        prices = [10.0 + i * 0.05 for i in range(n_rows)]
    else:
        prices = [50.0 - i * 0.05 for i in range(n_rows)]
        
    df = pd.DataFrame({
        "ts": dates,
        "o": prices,
        "h": [p + 0.1 for p in prices],
        "l": [p - 0.1 for p in prices],
        "c": prices,
        "v": [1000] * n_rows,
        "adj_close": prices
    })
    
    if breakout_idx is not None:
        df.loc[breakout_idx, "v"] = 5000
        prev_max = df.loc[breakout_idx - 20 : breakout_idx - 1, "h"].max()
        df.loc[breakout_idx, "c"] = prev_max + 0.5
        df.loc[breakout_idx, "adj_close"] = prev_max + 0.5
        df.loc[breakout_idx, "h"] = prev_max + 0.6
        
    return df

# ===========================================================================
# FEATURE A: Ingestion & Storage
# ===========================================================================

def test_A1_db_creation(sandbox_config):
    db_path = sandbox_config.get("data", "db_path")
    initialize_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ohlcv'")
        assert cursor.fetchone() is not None
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_ohlcv_ticker_ts'")
        assert cursor.fetchone() is not None

def test_A2_normal_ingestion(sandbox_config):
    db_path = sandbox_config.get("data", "db_path")
    initialize_db(db_path)
    df = pd.DataFrame({
        "ticker": ["PETR4", "PETR4"],
        "ts": [date(2024, 6, 20), date(2024, 6, 21)],
        "o": [30.0, 31.0],
        "h": [32.0, 33.0],
        "l": [29.0, 30.0],
        "c": [31.5, 32.5],
        "v": [1000, 2000],
        "adj_close": [31.5, 32.5]
    })
    saved = save_ohlcv(df, source="test", db_path=db_path)
    assert saved == 2
    loaded = load_ohlcv("PETR4", db_path=db_path)
    assert len(loaded) == 2
    assert loaded["c"].iloc[0] == 31.5
    assert loaded["ticker"].iloc[0] == "PETR4"

def test_A3_duplicate_ignoring(sandbox_config):
    db_path = sandbox_config.get("data", "db_path")
    initialize_db(db_path)
    df = pd.DataFrame({
        "ticker": ["PETR4"],
        "ts": [date(2024, 6, 20)],
        "o": [30.0],
        "h": [32.0],
        "l": [29.0],
        "c": [31.5],
        "v": [1000],
        "adj_close": [31.5]
    })
    saved1 = save_ohlcv(df, source="test", db_path=db_path)
    assert saved1 == 1
    saved2 = save_ohlcv(df, source="test", db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM ohlcv")
        count = cursor.fetchone()[0]
        assert count == 1

def test_A4_delta_start(sandbox_config, mock_b3_clock):
    db_path = sandbox_config.get("data", "db_path")
    initialize_db(db_path)
    start_empty = get_delta_start("PETR4", db_path=db_path)
    assert start_empty == clock.today_b3() - timedelta(days=365 * 5)
    
    df = pd.DataFrame({
        "ticker": ["PETR4"],
        "ts": [date(2024, 6, 20)],
        "o": [30.0],
        "h": [32.0],
        "l": [29.0],
        "c": [31.5],
        "v": [1000],
        "adj_close": [31.5]
    })
    save_ohlcv(df, source="test", db_path=db_path)
    start_pop = get_delta_start("PETR4", db_path=db_path)
    assert start_pop == date(2024, 6, 21)

def test_A5_yf_index_flattening(sandbox_config):
    multi_cols = pd.MultiIndex.from_tuples([("Close", "PETR4"), ("Open", "PETR4")])
    mock_df = pd.DataFrame([[30.0, 29.0]], columns=multi_cols, index=pd.to_datetime([date(2024, 6, 20)]))
    mock_df.index.name = "Date"
    
    with patch("yfinance.download", return_value=mock_df):
        res = fetch_yfinance("PETR4", start=date(2024, 6, 20), end=date(2024, 6, 20))
        assert "c" in res.columns
        assert "o" in res.columns

def test_A6_delisted_empty_response(sandbox_config):
    with patch("yfinance.download", return_value=pd.DataFrame()):
        res = fetch_yfinance("DELISTED", start=date(2024, 6, 20))
        assert res.empty
        assert list(res.columns) == ["ticker", "ts", "o", "h", "l", "c", "v", "adj_close"]

def test_A7_malformed_input_schema():
    df = pd.DataFrame({
        "Close": [30.0]
    })
    with pytest.raises(ValueError, match="Coluna de data não encontrada"):
        _normalize(df, "PETR4")

def test_A8_missing_adj_close():
    df = pd.DataFrame({
        "Close": [30.0],
        "Open": [29.0]
    }, index=pd.to_datetime([date(2024, 6, 20)]))
    df.index.name = "Date"
    normalized = _normalize(df, "PETR4")
    assert "adj_close" in normalized.columns
    assert normalized["adj_close"].iloc[0] == 30.0

def test_A9_negative_years(sandbox_config):
    with patch("yfinance.download", return_value=pd.DataFrame()):
        res = fetch_yfinance("PETR4", start=date(2026, 6, 20), end=date(2024, 6, 20))
        assert res.empty

def test_A10_locked_db(sandbox_config):
    db_path = sandbox_config.get("data", "db_path")
    df = pd.DataFrame({
        "ticker": ["PETR4"],
        "ts": [date(2024, 6, 20)],
        "o": [30.0],
        "h": [32.0],
        "l": [29.0],
        "c": [31.5],
        "v": [1000],
        "adj_close": [31.5]
    })
    with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("database is locked")):
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            save_ohlcv(df, db_path=db_path)

# ===========================================================================
# FEATURE B: Quality Validation
# ===========================================================================

def test_B11_clean_data_validation():
    df = pd.DataFrame({
        "ts": [date(2024, 6, 1), date(2024, 6, 2), date(2024, 6, 3)],
        "o": [30.0, 30.2, 30.4],
        "h": [30.5, 30.7, 30.9],
        "l": [29.8, 30.0, 30.2],
        "c": [30.2, 30.4, 30.6],
        "v": [1000, 1100, 1200],
        "adj_close": [30.2, 30.4, 30.6]
    })
    report = validate_ohlcv(df, "PETR4")
    assert report.ok
    assert len(report.issues) == 0

def test_B12_gap_warning():
    df = pd.DataFrame({
        "ts": [date(2024, 6, 1), date(2024, 6, 8)],
        "o": [30.0, 30.2],
        "h": [30.5, 30.7],
        "l": [29.8, 30.0],
        "c": [30.2, 30.4],
        "v": [1000, 1100],
        "adj_close": [30.2, 30.4]
    })
    report = validate_ohlcv(df, "PETR4")
    assert len(report.warnings) == 1
    assert report.warnings[0].issue_type == "gap"
    assert report.warnings[0].severity == "warning"

def test_B13_gap_error():
    df = pd.DataFrame({
        "ts": [date(2024, 6, 1), date(2024, 6, 13)],
        "o": [30.0, 30.2],
        "h": [30.5, 30.7],
        "l": [29.8, 30.0],
        "c": [30.2, 30.4],
        "v": [1000, 1100],
        "adj_close": [30.2, 30.4]
    })
    report = validate_ohlcv(df, "PETR4")
    assert len(report.errors) == 1
    assert report.errors[0].issue_type == "gap"
    assert report.errors[0].severity == "error"

def test_B14_zero_volume_warning():
    df = pd.DataFrame({
        "ts": [date(2024, 6, 1), date(2024, 6, 2)],
        "o": [30.0, 30.2],
        "h": [30.5, 30.7],
        "l": [29.8, 30.0],
        "c": [30.2, 30.4],
        "v": [1000, 0],
        "adj_close": [30.2, 30.4]
    })
    report = validate_ohlcv(df, "PETR4")
    assert len(report.warnings) == 1
    assert report.warnings[0].issue_type == "zero_volume"

def test_B15_large_price_move_warning_error():
    df = pd.DataFrame({
        "ts": [date(2024, 6, 1), date(2024, 6, 2), date(2024, 6, 3)],
        "o": [30.0, 30.0, 30.0],
        "h": [30.5, 39.0, 60.0],
        "l": [29.8, 29.8, 29.8],
        "c": [30.0, 37.5, 55.0],
        "v": [1000, 1000, 1000],
        "adj_close": [30.0, 37.5, 55.0]
    })
    report = validate_ohlcv(df, "PETR4")
    assert len(report.warnings) == 1
    assert report.warnings[0].issue_type == "large_move"
    assert len(report.errors) == 1
    assert report.errors[0].issue_type == "large_move"

def test_B16_empty_validation_input():
    df = pd.DataFrame()
    report = validate_ohlcv(df, "PETR4")
    assert not report.ok
    assert len(report.errors) == 1
    assert report.errors[0].issue_type == "empty"

def test_B17_single_row_input():
    df = pd.DataFrame({
        "ts": [date(2024, 6, 1)],
        "o": [30.0],
        "h": [30.5],
        "l": [29.8],
        "c": [30.2],
        "v": [1000],
        "adj_close": [30.2]
    })
    report = validate_ohlcv(df, "PETR4")
    assert report.ok
    assert len(report.issues) == 0

def test_B18_duplicate_timestamps():
    df = pd.DataFrame({
        "ts": [date(2024, 6, 1), date(2024, 6, 1)],
        "o": [30.0, 30.0],
        "h": [30.5, 30.5],
        "l": [29.8, 29.8],
        "c": [30.2, 30.2],
        "v": [1000, 1000],
        "adj_close": [30.2, 30.2]
    })
    report = validate_ohlcv(df, "PETR4")
    assert report.ok

def test_B19_zero_price_division_safety():
    df = pd.DataFrame({
        "ts": [date(2024, 6, 1), date(2024, 6, 2)],
        "o": [0.0, 30.0],
        "h": [0.0, 30.5],
        "l": [0.0, 29.8],
        "c": [0.0, 30.2],
        "v": [1000, 1000],
        "adj_close": [0.0, 30.2]
    })
    report = validate_ohlcv(df, "PETR4")
    assert isinstance(report.ok, bool)

def test_B20_weekends_holidays_exclusion():
    df = pd.DataFrame({
        "ts": [date(2024, 6, 7), date(2024, 6, 10)],
        "o": [30.0, 30.2],
        "h": [30.5, 30.7],
        "l": [29.8, 30.0],
        "c": [30.2, 30.4],
        "v": [1000, 1100],
        "adj_close": [30.2, 30.4]
    })
    report = validate_ohlcv(df, "PETR4")
    assert len(report.warnings) == 0

# ===========================================================================
# FEATURE C: Source Cross-Validation
# ===========================================================================

def test_C21_successful_check_less_than_05():
    df_yf = pd.DataFrame({"c": [35.5], "ts": [date(2024, 6, 30)]})
    df_brapi = pd.DataFrame({"c": [35.5], "ts": [date(2024, 6, 30)]})
    with patch("trading_bot.data.cross_validation.fetch_yfinance", return_value=df_yf), \
         patch("trading_bot.data.cross_validation.fetch_brapi", return_value=df_brapi):
        res = validate_ticker_current_quote("PETR4", "TOKEN")
        assert res["status"] == "ok"
        assert res["divergence_pct"] == 0.0

def test_C22_failed_check_greater_than_05():
    df_yf = pd.DataFrame({"c": [35.0], "ts": [date(2024, 6, 30)]})
    df_brapi = pd.DataFrame({"c": [35.5], "ts": [date(2024, 6, 30)]})
    with patch("trading_bot.data.cross_validation.fetch_yfinance", return_value=df_yf), \
         patch("trading_bot.data.cross_validation.fetch_brapi", return_value=df_brapi):
        res = validate_ticker_current_quote("PETR4", "TOKEN")
        assert res["status"] == "divergence_exceeded"
        assert res["divergence_pct"] > 0.5

def test_C23_skip_brapi_status_check(tmp_path):
    mock_adj = {
        "status": "ok",
        "max_divergence_pct": 0.0,
        "mean_divergence_pct": 0.0,
        "samples": 10,
        "ex_date_check": [],
        "errors": []
    }
    with patch("trading_bot.data.cross_validation.validate_ticker_adjustment_consistency", return_value=mock_adj):
        res = run_cross_validation(["PETR4"], brapi_token="", report_dir=tmp_path)
        assert res["status"] == "passed"
        assert res["results"][0]["cross_quote_check"]["status"] == "skipped"

def test_C24_ex_dividend_check_within_15():
    dt_pre = date(2023, 8, 13)
    dt_ex = date(2023, 8, 14)
    df_yf = pd.DataFrame({
        "ts": [dt_pre, dt_ex],
        "adj_close": [30.0, 28.7],
        "c": [30.0, 28.7]
    })
    raw_df = pd.DataFrame({
        "Close": [30.0, 28.7],
        "Adj Close": [30.0, 28.7]
    }, index=pd.to_datetime([dt_pre, dt_ex]))
    raw_df.index.name = "Date"
    
    with patch("trading_bot.data.cross_validation.today_b3", return_value=date(2023, 9, 1)), \
         patch("trading_bot.data.cross_validation.fetch_yfinance", return_value=df_yf), \
         patch("yfinance.download", return_value=raw_df):
        res = validate_ticker_adjustment_consistency("PETR4", overlap_days=90)
        assert len(res["ex_date_check"]) > 0
        assert res["ex_date_check"][0]["ok"] == True

def test_C25_json_report_validation(tmp_path):
    mock_adj = {
        "status": "ok",
        "max_divergence_pct": 0.0,
        "mean_divergence_pct": 0.0,
        "samples": 10,
        "ex_date_check": [],
        "errors": []
    }
    with patch("trading_bot.data.cross_validation.validate_ticker_adjustment_consistency", return_value=mock_adj):
        res = run_cross_validation(["PETR4"], brapi_token="", report_dir=tmp_path)
        report_file = tmp_path / f"cross_validation_{clock.today_b3().strftime('%Y%m%d')}.json"
        assert report_file.exists()
        with open(report_file) as f:
            data = json.load(f)
        assert data["status"] == "passed"
        assert "results" in data

def test_C26_missing_token_warning(tmp_path):
    mock_adj = {
        "status": "ok",
        "max_divergence_pct": 0.0,
        "mean_divergence_pct": 0.0,
        "samples": 10,
        "ex_date_check": [],
        "errors": []
    }
    with patch("trading_bot.data.cross_validation.validate_ticker_adjustment_consistency", return_value=mock_adj):
        res = run_cross_validation(["PETR4"], brapi_token="", report_dir=tmp_path)
        assert res["results"][0]["cross_quote_check"]["status"] == "skipped"

def test_C27_brapi_timeout_retries():
    call_count = 0
    def mock_get_retry(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise requests.RequestException("Timeout!")
        brapi_payload = {
            "results": [{
                "symbol": "PETR4",
                "historicalDataPrice": [{
                    "date": 1719705600,
                    "open": 35.0,
                    "high": 36.0,
                    "low": 34.5,
                    "close": 35.5,
                    "volume": 10000000,
                    "adjustedClose": 35.5
                }]
            }]
        }
        return MockResponse(brapi_payload, 200)

    with patch("requests.get", mock_get_retry), \
         patch("time.sleep", return_value=None):
        df = fetch_brapi("PETR4", token="TOKEN")
        assert not df.empty
        assert call_count == 3

def test_C28_429_rate_limit_backoff():
    call_count = 0
    sleeps = []
    
    def mock_get_fail(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise requests.RequestException("Rate Limit!")
        
    def mock_sleep(seconds):
        sleeps.append(seconds)
        
    with patch("requests.get", mock_get_fail), \
         patch("time.sleep", mock_sleep), \
         pytest.raises(requests.RequestException):
        fetch_brapi("PETR4", token="TOKEN", max_retries=3, backoff=2.0)
        
    assert call_count == 3
    assert len(sleeps) == 2
    assert sleeps == [2.0, 4.0]

def test_C29_invalid_mismatched_ticker_on_brapi():
    mock_resp = MockResponse({"error": True, "code": "NOT_FOUND", "message": "Ticker PETR44 not found"}, 200)
    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="Erro da API para PETR44"):
            fetch_brapi("PETR44", token="TOKEN")

def test_C30_yfinance_download_failure_recovery():
    with patch("trading_bot.data.cross_validation.fetch_yfinance", side_effect=Exception("Connection aborted")):
        res = validate_ticker_adjustment_consistency("PETR4")
        assert res["status"] == "error"
        assert "yfinance: Connection aborted" in res["errors"]

# ===========================================================================
# FEATURE D: Backtest Trade Execution
# ===========================================================================

def test_D31_breakout_signal_trigger():
    df = _generate_synthetic_data(n_rows=210, trend="up", breakout_idx=209)
    c = compute_signal(df, "PETR4", rsi_max=100.0, sma_trend_period=100)
    assert c is not None
    assert c.ticker == "PETR4"
    assert c.entry_price > 10.0

def test_D32_next_day_open_fill():
    df = _generate_synthetic_data(n_rows=250, trend="up", breakout_idx=210)
    df.loc[211, "o"] = 35.0
    df.loc[211, "l"] = 34.5
    df.loc[211, "h"] = 35.5
    df.loc[211, "c"] = 35.0
    df.loc[211, "adj_close"] = 35.0
    data = {"PETR4": df}
    res = run_regime_backtest(
        data=data,
        regime_name="test",
        start=df["ts"].iloc[0],
        end=df["ts"].iloc[245],
        capital=1000.0,
        ibov_filter=False,
        signal_params={"rsi_max": 100.0, "sma_trend_period": 100}
    )
    assert len(res.trades) > 0
    trade = res.trades[0]
    assert trade.entry_price == 35.0

def test_D33_take_profit_target_hit():
    df = _generate_synthetic_data(n_rows=250, trend="up", breakout_idx=210)
    df.loc[211, "o"] = 30.0
    df.loc[211, "c"] = 30.0
    df.loc[211, "h"] = 30.5
    df.loc[211, "l"] = 29.5
    df.loc[211, "adj_close"] = 30.0
    
    df.loc[212, "h"] = 34.0
    df.loc[212, "l"] = 29.5
    df.loc[212, "c"] = 32.0
    df.loc[212, "adj_close"] = 32.0
    
    data = {"PETR4": df}
    res = run_regime_backtest(
        data=data,
        regime_name="test",
        start=df["ts"].iloc[0],
        end=df["ts"].iloc[245],
        capital=1000.0,
        ibov_filter=False,
        signal_params={"rsi_max": 100.0, "sma_trend_period": 100}
    )
    assert len(res.trades) > 0
    trade = res.trades[0]
    assert trade.exit_reason == "target"
    assert abs(trade.exit_price - 33.0) <= 0.05

def test_D34_stop_loss_hit():
    df = _generate_synthetic_data(n_rows=250, trend="up", breakout_idx=210)
    df.loc[211, "o"] = 30.0
    df.loc[211, "c"] = 30.0
    df.loc[211, "h"] = 30.5
    df.loc[211, "l"] = 29.5
    df.loc[211, "adj_close"] = 30.0
    
    df.loc[212, "l"] = 27.0
    df.loc[212, "adj_close"] = 28.0
    
    data = {"PETR4": df}
    res = run_regime_backtest(
        data=data,
        regime_name="test",
        start=df["ts"].iloc[0],
        end=df["ts"].iloc[245],
        capital=1000.0,
        ibov_filter=False,
        signal_params={"rsi_max": 100.0, "sma_trend_period": 100, "stop_pct": 0.04}
    )
    assert len(res.trades) > 0
    trade = res.trades[0]
    assert trade.exit_reason == "stop"

def test_D35_15_day_timeout_exit():
    df = _generate_synthetic_data(n_rows=260, trend="up", breakout_idx=210)
    df.loc[211, "o"] = 30.0
    df.loc[211, "c"] = 30.0
    df.loc[211, "h"] = 30.5
    df.loc[211, "l"] = 29.5
    df.loc[211, "adj_close"] = 30.0
    
    for idx in range(212, 240):
        df.loc[idx, "o"] = 30.0
        df.loc[idx, "c"] = 30.0
        df.loc[idx, "h"] = 30.5
        df.loc[idx, "l"] = 29.5
        df.loc[idx, "adj_close"] = 30.0
        
    data = {"PETR4": df}
    res = run_regime_backtest(
        data=data,
        regime_name="test",
        start=df["ts"].iloc[0],
        end=df["ts"].iloc[245],
        capital=1000.0,
        ibov_filter=False,
        max_hold_days=15,
        signal_params={"rsi_max": 100.0, "sma_trend_period": 100}
    )
    assert len(res.trades) > 0
    timeout_trades = [t for t in res.trades if t.exit_reason == "timeout"]
    assert len(timeout_trades) > 0

def test_D36_gap_down_below_stop_abort():
    df = _generate_synthetic_data(n_rows=210, trend="up", breakout_idx=209)
    df.loc[210, "o"] = 5.0
    df.loc[210, "c"] = 5.0
    df.loc[210, "h"] = 5.1
    df.loc[210, "l"] = 4.9
    
    data = {"PETR4": df}
    res = run_regime_backtest(
        data=data,
        regime_name="test",
        start=df["ts"].iloc[0],
        end=df["ts"].iloc[205],
        capital=1000.0,
        ibov_filter=False,
        signal_params={"rsi_max": 100.0, "sma_trend_period": 100}
    )
    assert len(res.trades) == 0

def test_D37_intraday_stop_target_double_trigger():
    df = _generate_synthetic_data(n_rows=250, trend="up", breakout_idx=210)
    df.loc[211, "o"] = 30.0
    df.loc[211, "c"] = 30.0
    df.loc[211, "h"] = 30.5
    df.loc[211, "l"] = 29.5
    df.loc[211, "adj_close"] = 30.0
    
    df.loc[212, "h"] = 35.0
    df.loc[212, "l"] = 27.0
    
    data = {"PETR4": df}
    res = run_regime_backtest(
        data=data,
        regime_name="test",
        start=df["ts"].iloc[0],
        end=df["ts"].iloc[245],
        capital=1000.0,
        ibov_filter=False,
        signal_params={"rsi_max": 100.0, "sma_trend_period": 100, "stop_pct": 0.04}
    )
    assert len(res.trades) > 0
    trade = res.trades[0]
    assert trade.exit_reason == "stop"

def test_D38_same_day_entry_exit():
    df = _generate_synthetic_data(n_rows=250, trend="up", breakout_idx=210)
    df.loc[211, "o"] = 30.0
    df.loc[211, "c"] = 30.0
    df.loc[211, "l"] = 28.0
    
    data = {"PETR4": df}
    res = run_regime_backtest(
        data=data,
        regime_name="test",
        start=df["ts"].iloc[0],
        end=df["ts"].iloc[245],
        capital=1000.0,
        ibov_filter=False,
        signal_params={"rsi_max": 100.0, "sma_trend_period": 100, "stop_pct": 0.04}
    )
    assert len(res.trades) > 0
    trade = res.trades[0]
    assert trade.entry_date == trade.exit_date
    assert trade.exit_reason == "stop"

def test_D39_cash_exhaustion_sizing_block():
    df = _generate_synthetic_data(n_rows=210, trend="up", breakout_idx=209)
    data = {"PETR4": df}
    res = run_regime_backtest(
        data=data,
        regime_name="test",
        start=df["ts"].iloc[0],
        end=df["ts"].iloc[205],
        capital=4.0,
        ibov_filter=False,
        signal_params={"rsi_max": 100.0, "sma_trend_period": 100}
    )
    assert len(res.trades) == 0

def test_D40_corrupt_missing_ibov_index_trend_filter_default():
    df = _generate_synthetic_data(n_rows=250, trend="up", breakout_idx=210)
    data = {"PETR4": df}
    with patch("trading_bot.backtest.engine.get_ibov_data", return_value=None):
        res = run_regime_backtest(
            data=data,
            regime_name="test",
            start=df["ts"].iloc[0],
            end=df["ts"].iloc[245],
            capital=1000.0,
            ibov_filter=True,
            signal_params={"rsi_max": 100.0, "sma_trend_period": 100}
        )
        assert len(res.trades) > 0

# ===========================================================================
# FEATURE E: Performance Metrics & Gates
# ===========================================================================

def test_E41_aggregate_sharpe_ratio_computation():
    t1 = Trade("PETR4", date(2024, 6, 1), date(2024, 6, 5), 30.0, 31.5, 29.0, 33.0, "target", 0.05, 50.0, 1000.0, 1.0)
    t2 = Trade("PETR4", date(2024, 6, 6), date(2024, 6, 10), 31.5, 33.0, 30.0, 34.5, "target", 0.05, 50.0, 1000.0, 1.0)
    t3 = Trade("PETR4", date(2024, 6, 11), date(2024, 6, 15), 33.0, 31.3, 31.5, 36.0, "stop", -0.05, -50.0, 1000.0, 1.0)
    
    res = BacktestResult(
        regime="test",
        start=date(2024, 6, 1),
        end=date(2024, 6, 30),
        initial_capital=1000.0,
        final_capital=1050.0,
        trades=[t1, t2, t3],
        equity_curve=[1000.0, 1050.0]
    )
    
    agg = compute_aggregate_metrics([res])
    assert agg.sharpe_aggregate > -10.0

def test_E42_max_drawdown_duration_calculation():
    equity = [100.0, 120.0, 90.0, 95.0, 130.0]
    dd, dur = _max_drawdown(equity)
    assert dd == -0.25
    assert dur == 2

def test_E43_profit_factor_calculation():
    t1 = Trade("PETR4", date(2024, 6, 1), date(2024, 6, 5), 30.0, 31.5, 29.0, 33.0, "target", 0.05, 50.0, 1000.0, 1.0)
    t2 = Trade("PETR4", date(2024, 6, 6), date(2024, 6, 10), 31.5, 33.0, 30.0, 34.5, "target", 0.05, 50.0, 1000.0, 1.0)
    t3 = Trade("PETR4", date(2024, 6, 11), date(2024, 6, 15), 33.0, 31.3, 31.5, 36.0, "stop", -0.05, -20.0, 1000.0, 1.0)
    pf = _profit_factor([t1, t2, t3])
    assert pf == 5.0

def test_E44_overnight_stress_gap_impact():
    t1 = Trade("PETR4", date(2024, 6, 1), date(2024, 6, 30), 30.0, 30.0, 29.0, 33.0, "end_of_period", 0.0, 0.0, 500.0, 1.0)
    t2 = Trade("VALE3", date(2024, 6, 1), date(2024, 6, 30), 80.0, 80.0, 77.0, 88.0, "end_of_period", 0.0, 0.0, 500.0, 1.0)
    impact = _stress_test_gap([t1, t2], -0.10)
    assert impact == -0.10

def test_E45_sharpe_gate_evaluation():
    t1 = Trade("PETR4", date(2024, 6, 1), date(2024, 6, 5), 30.0, 31.5, 29.0, 33.0, "target", 0.20, 200.0, 1000.0, 1.0)
    t2 = Trade("PETR4", date(2024, 6, 6), date(2024, 6, 10), 31.5, 33.0, 30.0, 34.5, "target", 0.20, 200.0, 1000.0, 1.0)
    t3 = Trade("PETR4", date(2024, 6, 11), date(2024, 6, 15), 33.0, 34.0, 31.5, 36.0, "target", 0.20, 200.0, 1000.0, 1.0)
    
    res = BacktestResult(
        regime="test",
        start=date(2024, 6, 1),
        end=date(2024, 6, 30),
        initial_capital=1000.0,
        final_capital=1600.0,
        trades=[t1, t2, t3],
        equity_curve=[1000.0, 1600.0]
    )
    agg = compute_aggregate_metrics([res], min_sharpe_per_regime=0.5, min_sharpe_aggregate=1.0)
    assert agg.overall_pass is True

def test_E46_insufficient_trades_sharpe_default():
    t1 = Trade("PETR4", date(2024, 6, 1), date(2024, 6, 5), 30.0, 31.5, 29.0, 33.0, "target", 0.05, 50.0, 1000.0, 1.0)
    t2 = Trade("PETR4", date(2024, 6, 6), date(2024, 6, 10), 31.5, 33.0, 30.0, 34.5, "target", 0.05, 50.0, 1000.0, 1.0)
    sharpe = _trade_sharpe([t1, t2], regime_days=30)
    assert sharpe == 0.0

def test_E47_zero_variance_standard_deviation_division_safety():
    t1 = Trade("PETR4", date(2024, 6, 1), date(2024, 6, 5), 30.0, 30.0, 29.0, 33.0, "target", 0.0, 0.0, 1000.0, 1.0)
    t2 = Trade("PETR4", date(2024, 6, 6), date(2024, 6, 10), 30.0, 30.0, 30.0, 34.5, "target", 0.0, 0.0, 1000.0, 1.0)
    t3 = Trade("PETR4", date(2024, 6, 11), date(2024, 6, 15), 30.0, 30.0, 31.5, 36.0, "target", 0.0, 0.0, 1000.0, 1.0)
    sharpe = _trade_sharpe([t1, t2, t3], regime_days=30)
    assert sharpe == 0.0

def test_E48_account_bankruptcy():
    equity = [100.0, 50.0, 0.0, -10.0]
    dd, dur = _max_drawdown(equity)
    assert dd == -1.1
    assert dur == 3

def test_E49_zero_duration_regime_division_safety():
    t1 = Trade("PETR4", date(2024, 6, 1), date(2024, 6, 5), 30.0, 31.5, 29.0, 33.0, "target", 0.05, 50.0, 1000.0, 1.0)
    t2 = Trade("PETR4", date(2024, 6, 6), date(2024, 6, 10), 31.5, 33.0, 30.0, 34.5, "target", 0.05, 50.0, 1000.0, 1.0)
    t3 = Trade("PETR4", date(2024, 6, 11), date(2024, 6, 15), 33.0, 34.5, 31.5, 36.0, "target", 0.06, 50.0, 1000.0, 1.0)
    sharpe = _trade_sharpe([t1, t2, t3], regime_days=0)
    assert sharpe > -10.0

def test_E50_zero_positions_stress_gap_default():
    t1 = Trade("PETR4", date(2024, 6, 1), date(2024, 6, 5), 30.0, 31.5, 29.0, 33.0, "target", 0.05, 50.0, 1000.0, 1.0)
    impact = _stress_test_gap([t1], -0.10)
    assert impact == 0.0
