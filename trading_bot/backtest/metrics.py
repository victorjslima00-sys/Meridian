"""
Módulo 2 — Métricas de Backtest
================================
Calcula Sharpe, Sortino, Calmar, drawdown, sequências de perdas,
stress test de gap overnight e profit factor.

Gates de saída (Fase 1):
  - Sharpe > 1.0 agregado
  - Nenhum regime com Sharpe < 0.5
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from trading_bot.backtest.engine import BacktestResult, Trade

logger = logging.getLogger(__name__)

RISK_FREE_RATE_ANNUAL = 0.10   # Selic aproximada (10% a.a.)
TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------------------------------
# Estrutura de métricas
# ---------------------------------------------------------------------------

@dataclass
class RegimeMetrics:
    regime: str
    n_trades: int
    win_rate: float
    profit_factor: float
    expectancy_pct: float        # Retorno esperado por trade em %
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown_pct: float
    max_drawdown_duration_days: int
    max_consecutive_losses: int
    worst_trade_pct: float
    total_return_pct: float
    annualized_return_pct: float
    stress_gap_10pct: float      # Impacto de gap -10% nas posições abertas
    stress_gap_15pct: float      # Impacto de gap -15% nas posições abertas
    passes_gate: bool            # Sharpe >= 0.5

    def summary(self) -> str:
        gate = "✅" if self.passes_gate else "❌"
        return (
            f"{gate} [{self.regime}] "
            f"Trades={self.n_trades} | WinRate={self.win_rate:.1%} | "
            f"Sharpe={self.sharpe:.2f} | MaxDD={self.max_drawdown_pct:.1%} | "
            f"PF={self.profit_factor:.2f} | TotalRet={self.total_return_pct:.1%}"
        )


@dataclass
class AggregateMetrics:
    regimes: list[RegimeMetrics]
    sharpe_aggregate: float
    all_regimes_pass: bool
    overall_pass: bool           # Gate Fase 1: Sharpe > 1.0 E todos regimes >= 0.5

    def summary(self) -> str:
        gate = "✅ PASSA GATE FASE 1" if self.overall_pass else "❌ REPROVADO"
        return (
            f"{gate} | Sharpe agregado={self.sharpe_aggregate:.2f} "
            f"| Todos regimes passam: {self.all_regimes_pass}"
        )


# ---------------------------------------------------------------------------
# Cálculos
# ---------------------------------------------------------------------------

def _returns_from_trades(trades: list[Trade]) -> list[float]:
    """Extrai lista de retornos percentuais dos trades fechados."""
    return [t.pnl_pct for t in trades if t.exit_reason != "end_of_period"]


def _equity_returns(equity: list[float]) -> np.ndarray:
    """Retornos diários da equity curve."""
    eq = np.array(equity)
    if len(eq) < 2:
        return np.array([])
    return np.diff(eq) / eq[:-1]


def _trade_sharpe(trades: list[Trade], regime_days: int) -> float:
    """
    Sharpe baseado em retornos por trade (padrão para swing trading).
    Annualiza pelo número de trades por ano (não por dias).
    Mais robusto que daily equity Sharpe para estratégias não continuamente investidas.
    """
    returns = [t.pnl_pct for t in trades]
    if len(returns) < 3:
        return 0.0
    arr = np.array(returns)
    mean_r = float(np.mean(arr))
    std_r  = float(np.std(arr, ddof=1))
    if std_r == 0:
        return 0.0
    # Annualização: trades por ano
    years = max(regime_days / TRADING_DAYS_PER_YEAR, 0.01)
    trades_per_year = len(trades) / years
    # Retorno risk-free por trade (convertido de anual para "por trade")
    rf_per_trade = RISK_FREE_RATE_ANNUAL / trades_per_year
    return float((mean_r - rf_per_trade) / std_r * (trades_per_year ** 0.5))


def _sortino(returns: np.ndarray) -> float:
    """Sortino ratio anualizado (penaliza apenas retornos negativos)."""
    if len(returns) < 2:
        return 0.0
    rf_daily = (1 + RISK_FREE_RATE_ANNUAL) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess = returns - rf_daily
    downside = returns[returns < 0]
    if len(downside) == 0 or np.std(downside) == 0:
        return float("inf")
    return float(np.mean(excess) / np.std(downside) * math.sqrt(TRADING_DAYS_PER_YEAR))


def _max_drawdown(equity: list[float]) -> tuple[float, int]:
    """
    Calcula max drawdown e duração máxima.
    Returns: (max_drawdown_pct, max_duration_days)
    """
    eq = np.array(equity)
    if len(eq) < 2:
        return 0.0, 0

    peak = np.maximum.accumulate(eq)
    drawdown = (eq - peak) / peak
    max_dd = float(drawdown.min())

    # Duração: número de períodos em drawdown contínuo
    in_dd = drawdown < 0
    max_dur = 0
    cur_dur = 0
    for d in in_dd:
        if d:
            cur_dur += 1
            max_dur = max(max_dur, cur_dur)
        else:
            cur_dur = 0

    return max_dd, max_dur


def _consecutive_losses(trades: list[Trade]) -> int:
    """Sequência máxima de trades perdedores consecutivos."""
    max_seq = 0
    cur_seq = 0
    for t in trades:
        if t.pnl_pct < 0:
            cur_seq += 1
            max_seq = max(max_seq, cur_seq)
        else:
            cur_seq = 0
    return max_seq


def _profit_factor(trades: list[Trade]) -> float:
    """Soma dos ganhos / soma das perdas (em termos absolutos)."""
    gains = sum(t.pnl_abs for t in trades if t.pnl_abs > 0)
    losses = abs(sum(t.pnl_abs for t in trades if t.pnl_abs < 0))
    if losses == 0:
        return float("inf") if gains > 0 else 1.0
    return gains / losses


def _stress_test_gap(trades: list[Trade], gap_pct: float = -0.10) -> float:
    """
    Simula impacto de um gap overnight (ex: -10%) nas posições abertas.
    Retorna o impacto total em % do capital alocado.
    """
    open_trades = [t for t in trades if t.exit_reason == "end_of_period"]
    if not open_trades:
        return 0.0

    total_capital = sum(t.capital_allocated for t in open_trades)
    if total_capital == 0:
        return 0.0

    # Gap: preço cai gap_pct instantaneamente → stop pode não pegar
    impact = sum(t.capital_allocated * gap_pct for t in open_trades)
    return impact / total_capital


# ---------------------------------------------------------------------------
# Interface principal
# ---------------------------------------------------------------------------

def compute_regime_metrics(result: BacktestResult, min_sharpe: float = 0.5) -> RegimeMetrics:
    """Calcula métricas completas para um único regime."""
    trades = result.trades
    closed = result.closed_trades
    equity = result.equity_curve

    # Dias do regime (para annualização)
    regime_days = max((result.end - result.start).days, 1)

    # Retornos da equity (para drawdown e Sortino)
    eq_returns = _equity_returns(equity)
    trade_returns = [t.pnl_pct for t in closed]

    # Win rate
    wins = [t for t in closed if t.pnl_pct > 0]
    win_rate = len(wins) / len(closed) if closed else 0.0

    # Retorno total e anualizado (usando capital explícito do resultado)
    if hasattr(result, 'initial_capital') and result.initial_capital > 0:
        total_ret = (result.final_capital - result.initial_capital) / result.initial_capital
    elif equity and len(equity) >= 2:
        total_ret = (equity[-1] - equity[0]) / equity[0]
    else:
        total_ret = 0.0

    years = max(regime_days / TRADING_DAYS_PER_YEAR, 0.01)
    ann_ret = (1 + total_ret) ** (1 / years) - 1 if total_ret > -1 else -1.0

    max_dd, max_dd_dur = _max_drawdown(equity)
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0.0

    # Sharpe trade-based (mais significativo para swing trading)
    sharpe = _trade_sharpe(closed, regime_days)

    # Sortino equity-based (mantido para referência)
    sortino = _sortino(eq_returns) if len(eq_returns) >= 3 else 0.0

    metrics = RegimeMetrics(
        regime=result.regime,
        n_trades=result.n_trades,
        win_rate=win_rate,
        profit_factor=_profit_factor(closed),
        expectancy_pct=float(np.mean(trade_returns)) if trade_returns else 0.0,
        sharpe=round(sharpe, 3),
        sortino=round(sortino, 3),
        calmar=round(calmar, 3),
        max_drawdown_pct=round(max_dd, 4),
        max_drawdown_duration_days=max_dd_dur,
        max_consecutive_losses=_consecutive_losses(closed),
        worst_trade_pct=min(trade_returns) if trade_returns else 0.0,
        total_return_pct=round(total_ret, 4),
        annualized_return_pct=round(ann_ret, 4),
        stress_gap_10pct=round(_stress_test_gap(trades, -0.10), 4),
        stress_gap_15pct=round(_stress_test_gap(trades, -0.15), 4),
        passes_gate=sharpe >= min_sharpe,
    )

    logger.info(metrics.summary())
    return metrics


def compute_aggregate_metrics(
    results: list[BacktestResult],
    min_sharpe_per_regime: float = 0.5,
    min_sharpe_aggregate: float = 1.0,
) -> AggregateMetrics:
    """
    Calcula métricas agregadas de todos os regimes com base em thresholds injetados.
    """
    regime_metrics = [compute_regime_metrics(r, min_sharpe_per_regime) for r in results]

    # Sharpe agregado: combina todos os trades fechados de todos os regimes
    all_closed: list[Trade] = []
    total_days = 0
    for r in results:
        all_closed.extend(r.closed_trades)
        total_days += max((r.end - r.start).days, 1)

    sharpe_agg = _trade_sharpe(all_closed, total_days) if len(all_closed) >= 3 else 0.0
    all_pass = all(m.passes_gate for m in regime_metrics)
    overall_pass = sharpe_agg >= min_sharpe_aggregate and all_pass

    agg = AggregateMetrics(
        regimes=regime_metrics,
        sharpe_aggregate=round(sharpe_agg, 3),
        all_regimes_pass=all_pass,
        overall_pass=overall_pass,
    )

    logger.info("=" * 60)
    logger.info("MÉTRICAS AGREGADAS — FASE 1")
    logger.info(agg.summary())
    for m in regime_metrics:
        logger.info("  %s", m.summary())
    logger.info("=" * 60)

    return agg
