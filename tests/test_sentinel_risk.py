"""
Testes unitarios para o Agente Sentinel de Risco e Integridade — Orion Governance
"""
import pytest
from trading_bot.data.quant.sentinel_risk import SentinelRiskEngine


def test_sentinel_risk_limits():
    sentinel = SentinelRiskEngine(max_drawdown_limit_pct=10.0, max_leverage=1.0)
    
    # Portfolio saudavel (drawdown 3%)
    assert sentinel.check_risk_breach(current_drawdown_pct=3.0) is False
    
    # Portfolio violando limite (drawdown 12%)
    assert sentinel.check_risk_breach(current_drawdown_pct=12.0) is True


def test_sentinel_circuit_breaker_trigger():
    sentinel = SentinelRiskEngine(max_drawdown_limit_pct=8.0)
    
    # Choque de mercado
    event = sentinel.evaluate_portfolio_state(
        portfolio_value=85000.0,
        peak_value=100000.0,  # 15% drawdown
        volatility_annual=0.45,
    )
    
    assert event["circuit_breaker_tripped"] is True
    assert event["action"] == "EMERGENCY_DELEVERAGE"
    assert event["recommended_risk_allocation"] == 0.0
