"""
Módulo 2 — Backtesting Engine (v2 — corrigido)
===============================================
v2 corrige dois bugs do v1:
  1. Capital de posições fechadas ao fim do período não era devolvido
  2. Equity curve não incluía valor MTM (mark-to-market) das posições abertas

Design: posições abertas armazenadas como dicts simples (não Trade completo),
toda a lógica de fechamento no loop principal.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from trading_bot.signals.engine import compute_signal, Candidate, get_ibov_data, ibov_in_uptrend

logger = logging.getLogger(__name__)

# Custos de transação (conservadores)
BROKERAGE_PCT = 0.0003   # 0.03% por lado
SPREAD_PCT    = 0.0002   # 0.02% estimado
ROUND_TRIP    = (BROKERAGE_PCT + SPREAD_PCT) * 2   # 0.10% total

# Regimes obrigatórios (plano v4)
REGIMES = [
    {"name": "crise_volatilidade", "start": "2020-03-01", "end": "2020-09-30"},
    {"name": "alta_juros",         "start": "2021-06-01", "end": "2022-12-31"},
    {"name": "recuperacao_lateral","start": "2023-01-01", "end": "2024-06-30"},
]


# ---------------------------------------------------------------------------
# Estruturas de dados
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    ticker: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    stop: float
    target: float
    exit_reason: str       # 'stop' | 'target' | 'timeout' | 'end_of_period'
    pnl_pct: float         # Retorno % (já descontado custo de round trip)
    pnl_abs: float         # Retorno R$
    capital_allocated: float
    signal_score: float


@dataclass
class BacktestResult:
    regime: str
    start: date
    end: date
    initial_capital: float
    final_capital: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def closed_trades(self) -> list[Trade]:
        """Trades que terminaram antes do fim do período (stop/target/timeout)."""
        return [t for t in self.trades if t.exit_reason != "end_of_period"]


# ---------------------------------------------------------------------------
# Posição aberta (estado interno do backtest)
# ---------------------------------------------------------------------------

@dataclass
class _OpenPos:
    ticker: str
    entry_date: date
    entry_price: float
    stop: float
    target: float
    capital: float       # Capital comprometido nesta posição
    score: float
    days_open: int = 0
    max_hold_days: int = 15


# ---------------------------------------------------------------------------
# Engine principal
# ---------------------------------------------------------------------------

def run_regime_backtest(
    data: dict[str, pd.DataFrame],
    regime_name: str,
    start: date,
    end: date,
    capital: float,
    kelly_fraction: float = 0.25,
    max_positions: int = 3,
    max_hold_days: int = 15,
    signal_params: Optional[dict] = None,
    ibov_filter: bool = True,          # Filtro macro: só opera quando IBOV > SMA-50
) -> BacktestResult:
    """
    Simula a estratégia em um regime de mercado.

    Capital accounting (corrigido v2):
      - capital_cash: dinheiro disponível (fora de posições)
      - capital_invested: soma das posições abertas (MTM diário)
      - equity = capital_cash + capital_invested
      - Ao fechar posição (stop/target/timeout/end_of_period):
          capital_cash += pos.capital + pnl_abs
    """
    signal_params = signal_params or {}
    initial_capital = capital

    # Carregar IBOV para filtro macro (se ativo)
    ibov_df = None
    if ibov_filter:
        ibov_df = get_ibov_data(date(start.year - 1, 1, 1))  # 1 ano antes p/ SMA-50

    # Filtrar dados para o período
    regime_data: dict[str, pd.DataFrame] = {}
    for ticker, df in data.items():
        df_r = df[(df["ts"] >= start) & (df["ts"] <= end)].copy()
        if len(df_r) >= 30:
            regime_data[ticker] = df_r.sort_values("ts").reset_index(drop=True)

    if not regime_data:
        logger.warning("[%s] Sem dados para o regime", regime_name)
        return BacktestResult(
            regime=regime_name, start=start, end=end,
            initial_capital=initial_capital, final_capital=initial_capital
        )

    # Todos os dias de pregão do período
    all_dates = sorted(set(
        ts for df in regime_data.values() for ts in df["ts"].tolist()
    ))

    logger.info("[%s] %s → %s | %d ativos | %d dias",
                regime_name, start, end, len(regime_data), len(all_dates))

    capital_cash = initial_capital
    open_positions: dict[str, _OpenPos] = {}
    trades: list[Trade] = []
    equity_curve: list[float] = []

    for current_date in all_dates:
        # ------------------------------------------------------------------
        # 1. Atualizar contagem de dias das posições abertas
        # ------------------------------------------------------------------
        for pos in open_positions.values():
            pos.days_open += 1

        # ------------------------------------------------------------------
        # 2. Fechar posições (stop / target / timeout)
        # ------------------------------------------------------------------
        to_close: list[tuple[str, float, str]] = []

        for ticker, pos in open_positions.items():
            df_t = regime_data.get(ticker)
            if df_t is None:
                continue

            row = df_t[df_t["ts"] == current_date]
            if row.empty:
                continue

            low  = float(row["l"].iloc[0])
            high = float(row["h"].iloc[0])
            close = float(row["c"].iloc[0])

            exit_price = None
            exit_reason = None

            if low <= pos.stop:
                exit_price = pos.stop
                exit_reason = "stop"
            elif high >= pos.target:
                exit_price = pos.target
                exit_reason = "target"
            elif pos.days_open >= pos.max_hold_days:
                exit_price = close
                exit_reason = "timeout"

            if exit_price is not None:
                to_close.append((ticker, exit_price, exit_reason))

        for ticker, exit_price, exit_reason in to_close:
            pos = open_positions.pop(ticker)
            pnl_pct = (exit_price / pos.entry_price - 1) - ROUND_TRIP
            pnl_abs = pos.capital * pnl_pct
            capital_cash += pos.capital + pnl_abs   # ← devolve capital (bug v1 corrigido)

            trades.append(Trade(
                ticker=ticker,
                entry_date=pos.entry_date,
                exit_date=current_date,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                stop=pos.stop,
                target=pos.target,
                exit_reason=exit_reason,
                pnl_pct=round(pnl_pct, 6),
                pnl_abs=round(pnl_abs, 2),
                capital_allocated=pos.capital,
                signal_score=pos.score,
            ))

        # ------------------------------------------------------------------
        # 3. Abrir novas posições (se há slots e IBOV em uptrend)
        # ------------------------------------------------------------------
        slots = max_positions - len(open_positions)
        market_ok = ibov_in_uptrend(ibov_df, current_date) if ibov_df is not None else True

        if slots > 0 and capital_cash > 10 and market_ok:
            candidates: list[Candidate] = []

            for ticker, df_t in regime_data.items():
                if ticker in open_positions:
                    continue
                df_hist = df_t[df_t["ts"] < current_date]
                if len(df_hist) < 200:   # Mínimo para SMA-200
                    continue
                try:
                    c = compute_signal(df_hist, ticker, **signal_params)
                    if c:
                        candidates.append(c)
                except Exception:
                    pass

            candidates.sort(key=lambda c: c.score, reverse=True)

            for c in candidates[:slots]:
                # Dimensionamento: kelly_fraction do equity total / max_positions
                equity_now = capital_cash + sum(p.capital for p in open_positions.values())
                pos_size = equity_now * kelly_fraction / max_positions
                pos_size = min(pos_size, capital_cash)  # Não alocar mais do que disponível

                if pos_size < 5:
                    continue

                capital_cash -= pos_size
                open_positions[c.ticker] = _OpenPos(
                    ticker=c.ticker,
                    entry_date=current_date,
                    entry_price=c.entry_price,
                    stop=c.stop,
                    target=c.target,
                    capital=pos_size,
                    score=c.score,
                    max_hold_days=max_hold_days,
                )

        # ------------------------------------------------------------------
        # 4. Equity curve = cash + MTM das posições abertas
        # ------------------------------------------------------------------
        mtm = 0.0
        for ticker, pos in open_positions.items():
            df_t = regime_data.get(ticker)
            if df_t is not None:
                row = df_t[df_t["ts"] == current_date]
                if not row.empty:
                    price = float(row["c"].iloc[0])
                    mtm += pos.capital * (price / pos.entry_price)
                else:
                    mtm += pos.capital  # Sem dado, usa custo
        equity_curve.append(capital_cash + mtm)

    # ------------------------------------------------------------------
    # 5. Fechar posições abertas no fim do regime (ao preço de fechamento)
    # ------------------------------------------------------------------
    for ticker, pos in open_positions.items():
        df_t = regime_data.get(ticker)
        if df_t is not None and not df_t.empty:
            last = df_t.iloc[-1]
            pnl_pct = (float(last["c"]) / pos.entry_price - 1) - ROUND_TRIP
            pnl_abs = pos.capital * pnl_pct
            capital_cash += pos.capital + pnl_abs   # ← devolve capital

            trades.append(Trade(
                ticker=ticker,
                entry_date=pos.entry_date,
                exit_date=last["ts"],
                entry_price=pos.entry_price,
                exit_price=float(last["c"]),
                stop=pos.stop,
                target=pos.target,
                exit_reason="end_of_period",
                pnl_pct=round(pnl_pct, 6),
                pnl_abs=round(pnl_abs, 2),
                capital_allocated=pos.capital,
                signal_score=pos.score,
            ))

    final_capital = capital_cash  # Todas posições fechadas

    logger.info("[%s] Concluído: %d trades | Capital: R$%.2f → R$%.2f (%.1f%%)",
                regime_name, len(trades), initial_capital, final_capital,
                (final_capital / initial_capital - 1) * 100)

    return BacktestResult(
        regime=regime_name,
        start=start,
        end=end,
        initial_capital=initial_capital,
        final_capital=final_capital,
        trades=trades,
        equity_curve=equity_curve,
    )


def run_full_backtest(
    data: dict[str, pd.DataFrame],
    capital: float,
    kelly_fraction: float = 0.25,
    max_positions: int = 3,
    max_hold_days: int = 15,
    signal_params: Optional[dict] = None,
    regimes: Optional[list[dict]] = None,
    ibov_filter: bool = True,
) -> list[BacktestResult]:
    """Roda backtest nos 3 regimes obrigatórios do plano v4."""
    regimes = regimes or REGIMES
    return [
        run_regime_backtest(
            data=data,
            regime_name=r["name"],
            start=date.fromisoformat(r["start"]),
            end=date.fromisoformat(r["end"]),
            capital=capital,
            kelly_fraction=kelly_fraction,
            max_positions=max_positions,
            max_hold_days=max_hold_days,
            signal_params=signal_params,
            ibov_filter=ibov_filter,
        )
        for r in regimes
    ]
