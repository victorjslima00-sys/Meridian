r"""
Motor de Cointegracao e Arbitragem Estatistica de Pares (Pairs Trading)
Head of Data Engineering: Orion
Meridian Technologies

Fundamentacao Matematica:
Stanford CS229 (Capitulo 1 — Linear Regression & Normal Equations, Andrew Ng & Tengyu Ma)
Equacoes Normais de Minimos Quadrados Fechados (CS229 p. 16, Eq. 16):
  \theta = (X^T X)^{-1} X^T y
Onde:
  X = [1, x] (Matriz de design com intercepto)
  \theta = [\alpha, \beta]^T (Razao de Hedge)
  Spread Estacionario: e_t = y_t - (\beta x_t + \alpha)
  Z-Score Normalizado: Z_t = \frac{e_t - \mu_e}{\sigma_e}
"""
from __future__ import annotations

import logging
from typing import Any, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class PairsCointegrationEngine:
    """
    Motor analitico para estrategias Market-Neutral (Long/Short) em pares de alta correlacao
    (ex: PETR4/PETR3, VALE3/CSNA3, BBAS3/BBDC4) com reversao a media estatistica.
    """

    def __init__(self, window: int = 60, zscore_threshold: float = 2.0):
        self.window = window
        self.zscore_threshold = zscore_threshold

    def compute_ols_hedge_ratio(self, x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
        """
        Calcula a solucao analitica fechada das Equacoes Normais do CS229:
        theta = (X^T X)^(-1) X^T y
        """
        n = len(x)
        X_design = np.column_stack([np.ones(n), x])
        # (X^T X)^(-1) X^T y
        XtX = np.dot(X_design.T, X_design)
        Xty = np.dot(X_design.T, y)
        theta = np.linalg.solve(XtX, Xty)
        alpha, beta = float(theta[0]), float(theta[1])
        return alpha, beta

    def calculate_pair_spread(self, x: Sequence[float], y: Sequence[float]) -> dict[str, Any]:
        """
        Calcula o spread estacionario e a serie temporal de Z-Score.
        """
        x_arr = np.array(x, dtype=float)
        y_arr = np.array(y, dtype=float)

        alpha, beta = self.compute_ols_hedge_ratio(x_arr, y_arr)
        spread = y_arr - (beta * x_arr + alpha)

        # Z-Score rolante ou global
        n = len(spread)
        zscore = np.zeros(n)
        for i in range(n):
            start_idx = max(0, i - self.window + 1)
            window_slice = spread[start_idx:i + 1]
            mu = np.mean(window_slice)
            sigma = np.std(window_slice)
            zscore[i] = (spread[i] - mu) / sigma if sigma > 1e-6 else 0.0

        return {
            "alpha": round(alpha, 4),
            "hedge_ratio": round(beta, 4),
            "spread": spread,
            "zscore": zscore,
        }

    def generate_signals(self, zscores: np.ndarray) -> np.ndarray:
        """
        Gera sinais reversivos de negociacao:
          +1: Compra Y, Vende X (Spread subavaliado)
          -1: Vende Y, Compra X (Spread superavaliado)
           0: Fechamento de posicao (Retorno a media)
        """
        signals = np.zeros(len(zscores))
        for i, z in enumerate(zscores):
            if z <= -self.zscore_threshold:
                signals[i] = 1.0
            elif z >= self.zscore_threshold:
                signals[i] = -1.0
            elif abs(z) <= 0.2:
                signals[i] = 0.0
        return signals
