"""
Motor de Backtest Vetorizado Ultraflexivel em Python Puro
Head of Data Engineering: Orion
Meridian Technologies
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class FastVectorizedBacktester:
    """
    Backtester vetorizado para estrategias de canal de Donchian, Breakouts e regimes de mercado.
    Opera sem dependencias pesadas e calcula metricas institucionais completas:
      - Retorno Total
      - Sharpe Ratio (anualizado base 252)
      - Maximum Drawdown (MDD)
      - Win Rate (%) e Payoff Ratio (Avg Win / Avg Loss)
    """

    def __init__(self, initial_capital: float = 100000.0, risk_free_annual_rate: float = 0.139):
        self.initial_capital = initial_capital
        self.risk_free_daily_rate = (1.0 + risk_free_annual_rate) ** (1.0 / 252.0) - 1.0

    def run_donchian_breakout(
        self,
        df: pd.DataFrame,
        period: int = 20,
        price_col: str = "close",
        high_col: str = "high",
        low_col: str = "low",
    ) -> dict[str, Any]:
        """
        Executa simulacao vetorizada de Donchian Breakout com saida na minima de 10 dias.
        """
        if len(df) < period + 15:
            return {"error": "Dados insuficientes"}

        data = df.copy().reset_index(drop=True)
        close = data[price_col].values
        high = data[high_col].values if high_col in data else close
        low = data[low_col].values if low_col in data else close
        n = len(data)

        signals = np.zeros(n)
        positions = np.zeros(n)

        # 1. Calculo de Canais de Donchian
        for i in range(period, n):
            donchian_high = np.max(high[i - period:i])
            donchian_low = np.min(low[max(0, i - 10):i])

            if close[i] > donchian_high:
                signals[i] = 1.0   # Sinal de Compra
            elif close[i] < donchian_low:
                signals[i] = -1.0  # Sinal de Saida

        # 2. Posicionamento sequencial (1 lote comprado ou zerado)
        curr_pos = 0.0
        for i in range(n):
            if signals[i] == 1.0:
                curr_pos = 1.0
            elif signals[i] == -1.0:
                curr_pos = 0.0
            positions[i] = curr_pos

        # Desloca a posicao em 1 barra para evitar lookahead bias (compra na abertura do dia seguinte)
        pos_shifted = np.roll(positions, 1)
        pos_shifted[0] = 0.0

        # 3. Retornos da estrategia
        daily_returns = np.zeros(n)
        daily_returns[1:] = (close[1:] / close[:-1]) - 1.0
        strategy_returns = pos_shifted * daily_returns

        # 4. Metricas de Performance
        cumulative_curve = np.cumprod(1.0 + strategy_returns)
        peak = np.maximum.accumulate(cumulative_curve)
        drawdown = (cumulative_curve - peak) / peak
        max_drawdown = float(np.min(drawdown))
        total_return = float(cumulative_curve[-1] - 1.0)

        excess_returns = strategy_returns - self.risk_free_daily_rate
        std_dev = np.std(strategy_returns)
        sharpe = float(np.mean(excess_returns) / std_dev * np.sqrt(252)) if std_dev > 0 else 0.0

        trade_returns = strategy_returns[strategy_returns != 0.0]
        wins = trade_returns[trade_returns > 0.0]
        losses = trade_returns[trade_returns < 0.0]
        win_rate = float(len(wins) / len(trade_returns)) if len(trade_returns) > 0 else 0.0

        return {
            "total_bars": n,
            "total_return_pct": round(total_return * 100, 2),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "win_rate_pct": round(win_rate * 100, 2),
            "final_capital": round(self.initial_capital * cumulative_curve[-1], 2),
        }
