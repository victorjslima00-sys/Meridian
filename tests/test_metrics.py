import pytest
from datetime import date
from trading_bot.backtest.engine import Trade, BacktestResult
from trading_bot.backtest.metrics import _trade_sharpe, _max_drawdown, compute_regime_metrics, compute_aggregate_metrics

def test_trade_sharpe_positive():
    trades = [
        Trade("A", date(2020,1,1), date(2020,1,10), 10.0, 11.0, 1.0, 0.10, "target", 0.10, 10.0, 100.0, 1.0),
        Trade("B", date(2020,1,1), date(2020,1,10), 10.0, 11.0, 1.0, 0.10, "target", 0.10, 10.0, 100.0, 1.0),
        Trade("C", date(2020,1,1), date(2020,1,10), 10.0,  9.5, -0.5, -0.05, "stop", -0.05, -5.0, 100.0, 1.0),
    ]
    sharpe = _trade_sharpe(trades, regime_days=252) # 1 ano
    assert sharpe > 0.0

def test_trade_sharpe_negative():
    trades = [
        Trade("A", date(2020,1,1), date(2020,1,10), 10.0,  9.0, -1.0, -0.10, "stop", -0.10, -10.0, 100.0, 1.0),
        Trade("B", date(2020,1,1), date(2020,1,10), 10.0,  9.0, -1.0, -0.10, "stop", -0.10, -10.0, 100.0, 1.0),
        Trade("C", date(2020,1,1), date(2020,1,10), 10.0, 10.5,  0.5,  0.05, "target", 0.05, 5.0, 100.0, 1.0),
    ]
    sharpe = _trade_sharpe(trades, regime_days=252)
    assert sharpe < 0.0

def test_trade_sharpe_empty_or_small():
    sharpe0 = _trade_sharpe([], regime_days=252)
    assert sharpe0 == 0.0
    t = Trade("A", date(2020,1,1), date(2020,1,10), 10.0, 11.0, 1.0, 0.10, "target", 0.10, 10.0, 100.0, 1.0)
    sharpe2 = _trade_sharpe([t], regime_days=252)
    assert sharpe2 == 0.0 # precisa de pelo menos 3 trades

def test_max_drawdown():
    # Equity curve que vai de 100 a 120, cai para 90, sobe para 130
    equity = [100.0, 110.0, 120.0, 105.0, 90.0, 100.0, 130.0]
    dd, dur = _max_drawdown(equity)
    assert dd == -0.25
    assert dur == 3

def test_compute_regime_metrics():
    trades = [
        Trade("A", date(2020,1,1), date(2020,1,10), 10.0, 11.0, 1.0, 0.10, "target", 0.10, 10.0, 100.0, 1.0),
        Trade("B", date(2020,1,1), date(2020,1,10), 10.0, 11.5, 1.5, 0.15, "target", 0.15, 15.0, 100.0, 1.0),
        Trade("C", date(2020,1,1), date(2020,1,10), 10.0, 12.0, 2.0, 0.20, "target", 0.20, 20.0, 100.0, 1.0),
        Trade("D", date(2020,1,1), date(2020,1,10), 10.0, 11.0, 1.0, 0.10, "target", 0.10, 10.0, 100.0, 1.0),
    ]
    res = BacktestResult(
        regime="teste",
        start=date(2020, 1, 1),
        end=date(2020, 12, 31),
        initial_capital=1000.0,
        final_capital=1100.0,
        trades=trades,
        equity_curve=[1000.0, 1050.0, 1100.0]
    )
    metrics = compute_regime_metrics(res, min_sharpe=0.1)
    assert metrics.passes_gate

def test_compute_aggregate_metrics():
    trades1 = [
        Trade("A", date(2020,1,1), date(2020,1,10), 10.0, 11.0, 1.0, 0.10, "target", 0.10, 10.0, 100.0, 1.0),
        Trade("B", date(2020,1,1), date(2020,1,10), 10.0, 12.0, 2.0, 0.20, "target", 0.20, 20.0, 100.0, 1.0),
        Trade("C", date(2020,1,1), date(2020,1,10), 10.0, 11.5, 1.5, 0.15, "target", 0.15, 15.0, 100.0, 1.0)
    ]
    trades2 = [
        Trade("D", date(2021,1,1), date(2021,1,10), 10.0, 11.0, 1.0, 0.10, "target", 0.10, 10.0, 100.0, 1.0),
        Trade("E", date(2021,1,1), date(2021,1,10), 10.0, 12.0, 2.0, 0.20, "target", 0.20, 20.0, 100.0, 1.0),
        Trade("F", date(2021,1,1), date(2021,1,10), 10.0, 11.5, 1.5, 0.15, "target", 0.15, 15.0, 100.0, 1.0)
    ]
    res1 = BacktestResult("r1", date(2020,1,1), date(2020,12,31), 1000.0, 1100.0, trades1, [1000.0, 1100.0])
    res2 = BacktestResult("r2", date(2021,1,1), date(2021,12,31), 1000.0, 1100.0, trades2, [1000.0, 1100.0])
    
    agg = compute_aggregate_metrics([res1, res2], min_sharpe_per_regime=0.1, min_sharpe_aggregate=0.1)
    assert agg.overall_pass
