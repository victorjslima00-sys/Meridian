r"""
Motor de Otimizacao de Portfolios & Teoria Moderna de Portfolios (Markowitz)
Head of Quantitative Analytics: Atlas
Meridian Technologies

Fundamentacao:
Teoria de Markowitz (Fronteira Eficiente e Maximizacao de Sharpe Ratio)
Retorno Esperado do Portfolio: \mu_p = w^T \mu
Variancia do Portfolio: \sigma_p^2 = w^T \Sigma w
Sharpe Ratio: S_p = \frac{\mu_p - R_f}{\sigma_p}
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class MarkowitzPortfolioOptimizer:
    """
    Otimizador de alocacao de capital e pesos de ativos na carteira do Meridian.
    Calcula alocacao de variancia minima e carteira de maximo Sharpe.
    """

    def __init__(self, risk_free_rate: float = 0.139):
        self.risk_free_rate = risk_free_rate

    def equal_weight_allocation(self, n_assets: int) -> np.ndarray:
        if n_assets <= 0:
            return np.array([])
        return np.ones(n_assets) / float(n_assets)

    def evaluate_portfolio(
        self,
        weights: np.ndarray,
        expected_returns: np.ndarray,
        cov_matrix: np.ndarray,
    ) -> dict[str, Any]:
        """
        Calcula retorno esperado, volatilidade e Sharpe ratio do portfolio.
        """
        w = weights.reshape(-1)
        r = expected_returns.reshape(-1)

        port_return = float(np.dot(w, r))
        port_variance = float(np.dot(w.T, np.dot(cov_matrix, w)))
        port_volatility = float(np.sqrt(max(port_variance, 1e-8)))

        excess_return = port_return - self.risk_free_rate
        sharpe = round(excess_return / port_volatility, 3)

        return {
            "expected_return": round(port_return, 4),
            "volatility": round(port_volatility, 4),
            "sharpe_ratio": sharpe,
        }
