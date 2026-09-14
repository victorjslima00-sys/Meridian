"""
Testes unitarios para o Filtro de Kalman de Tendencia e Ruido de Mercado — Orion Quant
Baseado no Stanford CS229 (Capitulo 20.4 — Linear Quadratic Gaussian & Kalman Filter)
"""
import numpy as np
import pandas as pd
import pytest
from trading_bot.data.quant.kalman_filter import MarketKalmanFilter


def test_kalman_filter_initialization():
    kf = MarketKalmanFilter(process_variance=1e-4, measurement_variance=1e-2)
    assert kf.process_variance == 1e-4
    assert kf.measurement_variance == 1e-2


def test_kalman_filter_noise_smoothing():
    kf = MarketKalmanFilter(process_variance=1e-3, measurement_variance=0.25)

    # Gera uma serie com tendencia linear + ruido gaussiano
    np.random.seed(42)
    n = 100
    true_trend = np.linspace(30.0, 35.0, n)
    noise = np.random.normal(0, 0.5, n)
    noisy_prices = true_trend + noise

    estimates, velocities = kf.filter_series(noisy_prices)

    assert len(estimates) == n
    assert len(velocities) == n

    # Ignora o periodo inicial de calibracao (burn-in de 15 passos)
    mse_noisy = np.mean((noisy_prices[15:] - true_trend[15:]) ** 2)
    mse_filtered = np.mean((estimates[15:] - true_trend[15:]) ** 2)
    assert mse_filtered < mse_noisy


def test_kalman_filter_dataframe_integration():
    kf = MarketKalmanFilter()
    df = pd.DataFrame({
        "ts": pd.date_range("2026-08-01", periods=10),
        "close": [30.1, 30.5, 30.2, 30.8, 31.0, 30.9, 31.5, 31.8, 31.6, 32.0],
    })

    res_df = kf.apply_to_dataframe(df, price_col="close")
    assert "kalman_trend" in res_df.columns
    assert "kalman_velocity" in res_df.columns
    assert "kalman_residual" in res_df.columns
    assert len(res_df) == 10
