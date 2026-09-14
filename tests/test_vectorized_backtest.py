"""
Testes unitarios para o Backtest Vetorizado Rapido — Orion Quant
"""
import numpy as np
import pandas as pd
import pytest
from trading_bot.data.quant.vectorized_backtest import FastVectorizedBacktester


def test_backtester_initialization():
    bt = FastVectorizedBacktester(initial_capital=50000.0, risk_free_annual_rate=0.10)
    assert bt.initial_capital == 50000.0
    assert bt.risk_free_daily_rate > 0


def test_backtester_run_synthetic_breakout():
    # Gera serie de 100 dias com forte tendencia de alta
    np.random.seed(42)
    n = 100
    prices = np.cumprod(1.0 + np.random.normal(0.002, 0.015, n)) * 30.0

    df = pd.DataFrame({
        "close": prices,
        "high": prices * 1.01,
        "low": prices * 0.99,
    })

    bt = FastVectorizedBacktester(initial_capital=100000.0)
    results = bt.run_donchian_breakout(df, period=20)

    assert "total_return_pct" in results
    assert "max_drawdown_pct" in results
    assert "sharpe_ratio" in results
    assert "win_rate_pct" in results
    assert results["total_bars"] == 100
