"""
Testes unitarios para o Motor de Otimizacao de Portfolios de Markowitz — Atlas Analytics
"""
import numpy as np
import pytest
from trading_bot.analytics.portfolio_optimizer import MarkowitzPortfolioOptimizer


def test_portfolio_optimizer_equal_weight_baseline():
    opt = MarkowitzPortfolioOptimizer(risk_free_rate=0.139)
    # 3 ativos com retornos medios anuais simulados
    expected_returns = np.array([0.18, 0.22, 0.15])
    cov_matrix = np.array([
        [0.04, 0.01, 0.005],
        [0.01, 0.06, 0.01],
        [0.005, 0.01, 0.03],
    ])
    
    weights = opt.equal_weight_allocation(n_assets=3)
    assert len(weights) == 3
    assert np.sum(weights) == pytest.approx(1.0)
    assert weights[0] == pytest.approx(1.0 / 3.0)


def test_portfolio_optimizer_metrics():
    opt = MarkowitzPortfolioOptimizer(risk_free_rate=0.139)
    expected_returns = np.array([0.18, 0.22, 0.15])
    cov_matrix = np.array([
        [0.04, 0.01, 0.005],
        [0.01, 0.06, 0.01],
        [0.005, 0.01, 0.03],
    ])
    weights = np.array([0.4, 0.4, 0.2])
    
    metrics = opt.evaluate_portfolio(weights, expected_returns, cov_matrix)
    assert "expected_return" in metrics
    assert "volatility" in metrics
    assert "sharpe_ratio" in metrics
    assert metrics["expected_return"] > 0.17
    assert metrics["volatility"] > 0.0
