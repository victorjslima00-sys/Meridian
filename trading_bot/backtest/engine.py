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

import pandas as pd

from trading_bot.signals.engine import compute_signal, Candidate, get_ibov_data, ibov_in_uptrend
from trading_bot.risk.position_sizing import calculate_position_size

logger = logging.getLogger(__name__)

# Custos de transação (injetados agora nos scripts)

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
    brokerage_pct: float = 0.0003,
    spread_pct: float = 0.0002,
    warmup_bars: int = 300,            # História ANTES de `start` só p/ indicadores
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
    round_trip = (brokerage_pct + spread_pct) * 2

    # Carregar IBOV para filtro macro (se ativo)
    ibov_df = None
    if ibov_filter:
        ibov_df = get_ibov_data(date(start.year - 1, 1, 1))  # 1 ano antes p/ SMA-50

    # Filtrar dados para o período — COM buffer de aquecimento.
    #
    # Antes, o corte era `df[(ts >= start) & (ts <= end)]` direto, ANTES de
    # qualquer indicador ser calculado. Como a abertura de posição exige
    # `len(df_hist) >= 200` (SMA-200), os primeiros 200 pregões de CADA janela
    # ficavam estruturalmente incapazes de gerar sinal. Medido nos regimes
    # reais: crise_volatilidade (148 pregões) tinha 0% da janela testável — o
    # `n=0 trades` dali era ARTEFATO DE MEDIÇÃO, não resultado; alta_juros
    # rodava 49% da janela e recuperacao_lateral 46%.
    #
    # O buffer traz barras ANTERIORES a `start` só como história de indicador.
    # Ele NÃO estende o período operado: `all_dates` abaixo continua restrito a
    # [start, end], então nenhuma entrada acontece fora do regime medido.
    regime_data: dict[str, pd.DataFrame] = {}
    for ticker, df in data.items():
        df_s = df.sort_values("ts")
        df_janela = df_s[(df_s["ts"] >= start) & (df_s["ts"] <= end)]
        # O mínimo de 30 barras vale para o que negociou DENTRO da janela: o
        # buffer não pode ressuscitar um ticker ausente no período.
        if len(df_janela) < 30:
            continue
        df_warm = df_s[df_s["ts"] < start].tail(warmup_bars)
        regime_data[ticker] = pd.concat([df_warm, df_janela]).reset_index(drop=True)

    if not regime_data:
        logger.warning("[%s] Sem dados para o regime", regime_name)
        return BacktestResult(
            regime=regime_name, start=start, end=end,
            initial_capital=initial_capital, final_capital=initial_capital
        )

    # Dias simulados = só os pregões DA JANELA (o buffer é história, não período)
    all_dates = sorted(set(
        ts for df in regime_data.values()
        for ts in df["ts"].tolist()
        if start <= ts <= end
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

            open_price = float(row["o"].iloc[0])
            low  = float(row["l"].iloc[0])
            high = float(row["h"].iloc[0])
            close = float(row["c"].iloc[0])

            exit_price = None
            exit_reason = None

            # 1. Se a abertura já violar o Stop, liquidado no preço de abertura (gap down)
            if open_price <= pos.stop:
                exit_price = open_price
                exit_reason = "stop_gap"
            # 2. Se a abertura já violar o Alvo, realiza lucro na abertura (gap up)
            elif open_price >= pos.target:
                exit_price = open_price
                exit_reason = "target_gap"
            # 3. Fluxo normal intra-day
            elif low <= pos.stop:
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
            pnl_pct = (exit_price / pos.entry_price - 1) - round_trip
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
                except Exception as e:
                    logger.debug("[%s] Erro no compute_signal: %s", ticker, e)

            candidates.sort(key=lambda c: c.score, reverse=True)

            for c in candidates[:slots]:
                # -------------------------------------------------------------
                # C1: Simulação real do preenchimento da ordem
                # -------------------------------------------------------------
                df_t = regime_data[c.ticker]
                today_row = df_t[df_t["ts"] == current_date]
                if today_row.empty:
                    continue

                open_price = float(today_row["o"].iloc[0])
                low = float(today_row["l"].iloc[0])
                high = float(today_row["h"].iloc[0])

                capital_invested = sum(p.capital for p in open_positions.values())
                pos_size = calculate_position_size(
                    capital_cash=capital_cash,
                    open_positions_capital=capital_invested,
                    kelly_fraction=kelly_fraction,
                    max_positions=max_positions,
                    current_open_count=len(open_positions)
                )

                if pos_size <= 0:
                    continue

                if capital_cash < pos_size:
                    logger.warning("[%s] Cash insuficiente p/ %s. Requerido: %.2f | Disp: %.2f",
                                   current_date, c.ticker, pos_size, capital_cash)
                    continue

                # Aborta se abriu abaixo do stop planejado
                if open_price <= c.stop:
                    logger.info("[%s] Entrada abortada por gap: open=%.2f <= stop original=%.2f",
                                 c.ticker, open_price, c.stop)
                    continue

                # Recalcula stop/target proporcionalmente ao fill real (open)
                stop_dist = (c.entry_price - c.stop) / c.entry_price
                target_dist = (c.target - c.entry_price) / c.entry_price
                
                entry_price_real = open_price
                stop_real = round(entry_price_real * (1 - stop_dist), 2)
                target_real = round(entry_price_real * (1 + target_dist), 2)

                capital_cash -= pos_size
                
                # Verifica se o novo stop/target foi atingido no PRÓPRIO DIA de entrada
                exit_price = None
                exit_reason = None
                
                if low <= stop_real:
                    exit_price = stop_real
                    exit_reason = "stop"
                elif high >= target_real:
                    exit_price = target_real
                    exit_reason = "target"
                    
                if exit_price is not None:
                    # Trade fechado no mesmo dia
                    pnl_pct = (exit_price / entry_price_real - 1) - round_trip
                    pnl_abs = pos_size * pnl_pct
                    capital_cash += pos_size + pnl_abs
                    
                    trades.append(Trade(
                        ticker=c.ticker,
                        entry_date=current_date,
                        exit_date=current_date,
                        entry_price=entry_price_real,
                        exit_price=exit_price,
                        stop=stop_real,
                        target=target_real,
                        exit_reason=exit_reason,
                        pnl_pct=round(pnl_pct, 6),
                        pnl_abs=round(pnl_abs, 2),
                        capital_allocated=pos_size,
                        signal_score=c.score,
                    ))
                else:
                    # Posição sobrevive ao primeiro dia
                    open_positions[c.ticker] = _OpenPos(
                        ticker=c.ticker,
                        entry_date=current_date,
                        entry_price=entry_price_real,
                        stop=stop_real,
                        target=target_real,
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
            pnl_pct = (float(last["c"]) / pos.entry_price - 1) - round_trip
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
    brokerage_pct: float = 0.0003,
    spread_pct: float = 0.0002,
    warmup_bars: int = 300,
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
            brokerage_pct=brokerage_pct,
            spread_pct=spread_pct,
            warmup_bars=warmup_bars,
        )
        for r in regimes
    ]
