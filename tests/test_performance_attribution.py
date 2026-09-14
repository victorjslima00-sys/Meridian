"""
Testes unitarios para o Motor de Relatorios de Atribuicao de Performance (Atlas Analytics)
"""
import pytest
from trading_bot.analytics.performance_attribution import PerformanceAttributionEngine


def test_performance_attribution_metrics():
    engine = PerformanceAttributionEngine()
    
    trades = [
        {"ticker": "PETR4", "pnl": 1250.0, "duration_days": 4, "type": "WIN"},
        {"ticker": "VALE3", "pnl": -450.0, "duration_days": 2, "type": "LOSS"},
        {"ticker": "PETR4", "pnl": 890.0, "duration_days": 5, "type": "WIN"},
        {"ticker": "BBAS3", "pnl": -300.0, "duration_days": 1, "type": "LOSS"},
    ]
    
    report = engine.generate_attribution_report(trades)
    
    assert report["total_trades"] == 4
    assert report["net_pnl"] == 1390.0
    assert report["win_rate_pct"] == 50.0
    assert report["profit_factor"] == pytest.approx(2.85, abs=0.05)
    assert "PETR4" in report["by_ticker"]
    assert report["by_ticker"]["PETR4"]["net_pnl"] == 2140.0
