import pytest
from datetime import date
from trading_bot.backtest.engine import Trade
from trading_bot.backtest.metrics import _trade_sharpe, _max_drawdown

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
