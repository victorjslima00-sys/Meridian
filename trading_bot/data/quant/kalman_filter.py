"""
Filtro de Kalman para Extracao de Tendencia Estocastica e Filtragem de Ruido de Mercado
Head of Data Engineering: Orion
Meridian Technologies

Fundamentacao Teorica:
Stanford CS229 (Capitulo 20.4 — Linear Quadratic Gaussian & Kalman Filter)
Modelo em Espaco de Estados com Modelo de Velocidade / Tendencia Local (2D State-Space):
  s_{t+1} = A s_t + w_t
  y_t     = C s_t + v_t
Onde:
  s_t = [posicao (preco), velocidade (inclinacao)]^T
  A   = [[1, 1], [0, 1]]
  C   = [1, 0]
"""
from __future__ import annotations

import logging
from typing import Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class MarketKalmanFilter:
    """
    Filtro de Kalman com espaco de estados bidimensional (preco + velocidade/momentum)
    capaz de rastrear tendencias sem atraso sistematico (lag) e filtrar o ruido de microestrutura.
    """

    def __init__(
        self,
        process_variance: float = 1e-3,     # Variancia da aceleracao/momentum
        measurement_variance: float = 0.25, # Variancia do ruido de cotacao (spread/slippage)
    ):
        self.process_variance = process_variance
        self.measurement_variance = measurement_variance

    def filter_series(self, prices: Sequence[float]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Executa a filtragem recursiva de Kalman com estado 2D [preco, velocidade].
        """
        n = len(prices)
        if n == 0:
            return np.array([]), np.array([])

        # Matrizes do sistema (CS229 Cap. 20.4)
        A = np.array([[1.0, 1.0], [0.0, 1.0]])   # Transicao de estado
        C = np.array([[1.0, 0.0]])               # Observador (observamos apenas o preco)
        Q = np.array([
            [self.process_variance / 4.0, self.process_variance / 2.0],
            [self.process_variance / 2.0, self.process_variance]
        ])                                       # Covariancia do processo
        R = np.array([[self.measurement_variance]]) # Covariancia da medicao

        # Inicializacao
        x_est = np.array([[float(prices[0])], [0.0]])
        P_est = np.array([[1.0, 0.0], [0.0, 1.0]])

        estimates = np.zeros(n)
        velocities = np.zeros(n)

        for i, price in enumerate(prices):
            # 1. Previsao (Predict Step)
            x_pred = A @ x_est
            P_pred = A @ P_est @ A.T + Q

            # 2. Inovacao e Ganho de Kalman
            y = np.array([[float(price)]])
            innovation = y - (C @ x_pred)
            S = C @ P_pred @ C.T + R
            K = P_pred @ C.T @ np.linalg.inv(S)

            # 3. Atualizacao (Update Step)
            x_est = x_pred + K @ innovation
            P_est = (np.eye(2) - K @ C) @ P_pred

            estimates[i] = x_est[0, 0]
            velocities[i] = x_est[1, 0]

        return estimates, velocities

    def apply_to_dataframe(
        self,
        df: pd.DataFrame,
        price_col: str = "close",
    ) -> pd.DataFrame:
        """
        Aplica o filtro ao DataFrame e enriquece com preco limpo e momentum latente.
        """
        if df.empty or price_col not in df.columns:
            return df

        out = df.copy()
        prices = out[price_col].values
        estimates, velocities = self.filter_series(prices)

        out["kalman_trend"] = estimates
        out["kalman_velocity"] = velocities
        out["kalman_residual"] = out[price_col] - out["kalman_trend"]

        return out
