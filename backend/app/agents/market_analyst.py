"""
MarketAnalyst — gerador de sinal de ENTRADA (Fase 1, Commit 2).

MUDANÇA ESTRUTURAL: o sinal volta a ser a estratégia DETERMINÍSTICA que
foi backtestada — Donchian breakout de 20 dias + filtro estrutural
SMA-200 + confirmação de volume + RSI, com stop/alvo por ATR, no
timeframe DIÁRIO, e filtro macro IBOV (> SMA-50). É exatamente
`trading_bot/signals/engine.py::compute_signal`, com os MESMOS parâmetros
que o backtest lê (config/settings.yaml::signals) — é isso que faz o
sinal ao vivo reproduzir o Sharpe medido no backtest.

O LLM SAIU COMPLETAMENTE do caminho de decisão de entrada. Não há
nenhuma chamada a generate_text aqui — nenhum import de ResilientLLMClient.
(Motivo raiz do que começou tudo: 47 chamadas Gemini/ciclo -> rate-limit
constante -> HOLD; timeframe 15min "parecia scalp"; e o sinal nunca fora
backtestado. Os três resolvidos ao voltar ao determinístico.) O LLM
retornará numa fase futura como CAMADA DE INTELIGÊNCIA (sentimento/regime)
— nunca como gatilho de trade.

Long-only: compute_signal é um breakout de COMPRA; devolve um Candidate
ou None. None -> HOLD. Não há mais SELL/short (o backtest é long-only).
"""
import asyncio
import logging
from typing import Any, Dict

import pandas as pd

from ..markets import resolve_market
from trading_bot.signals.engine import (
    compute_signal,
    get_ibov_data,
    ibov_in_uptrend,
)

logger = logging.getLogger(__name__)

# Mínimo de barras diárias: SMA-200 exige 200 de histórico + a barra atual.
_MIN_DAILY_BARS = 201


def _signal_params() -> Dict[str, Any]:
    """Parâmetros de PRODUÇÃO — a MESMA fonte que o backtest lê
    (config/settings.yaml::signals). Ler daqui, e o backtest ler daqui, é o
    que garante que ao vivo roda EXATAMENTE o que foi validado."""
    from trading_bot.core.config import AppConfig

    sig = AppConfig.load().get("signals", default={}) or {}
    return {
        "breakout_period": sig.get("breakout_period", 20),
        "volume_mult": sig.get("volume_multiplier", 1.5),
        "sma_trend_period": sig.get("sma_trend_period", 200),
        "rsi_max": sig.get("rsi_max", 75.0),
        "stop_atr_mult": sig.get("stop_atr_mult", 1.5),
        "stop_pct": sig.get("stop_pct", 0.04),
        "target_atr_mult": sig.get("target_atr_mult", 3.0),
    }


class MarketAnalyst:
    def __init__(self, ticker: str):
        self.ticker = ticker

    def _hold(self, reason: str, last_price: float = 0.0) -> Dict[str, Any]:
        return {
            "signal": "HOLD",
            "confidence": 0,
            "target_price": 0.0,
            "stop_loss": 0.0,
            "reason": reason,
            "last_price": float(last_price),
        }

    async def analyze(self) -> Dict[str, Any]:
        """Devolve o sinal do ticker: BUY (com alvo/stop por ATR) ou HOLD."""
        market = resolve_market(self.ticker)

        # Barras DIÁRIAS com histórico para SMA-200 + Donchian-20. O I/O de
        # rede roda numa thread (fetch_recent_data é síncrono/bloqueante).
        df = await asyncio.to_thread(
            market.fetch_ohlcv, self.ticker, period="2y", interval="1d"
        )
        if df is None or len(df) < _MIN_DAILY_BARS:
            return self._hold("Dados diários insuficientes para o sinal Donchian.")

        last_price = float(df["close"].iloc[-1])

        # Adapta o schema do feed (date/open/high/low/close/volume) ao que o
        # compute_signal espera (ts/adj_close/h/l/v). O feed usa
        # auto_adjust=True, então 'close' já é ajustado -> adj_close = close.
        eng_df = pd.DataFrame(
            {
                "ts": pd.to_datetime(df["date"]).dt.date,
                "adj_close": df["close"].astype(float),
                "h": df["high"].astype(float),
                "l": df["low"].astype(float),
                "v": df["volume"].astype(float),
            }
        )

        # Filtro macro IBOV (mesmo do backtest): só abre entrada com IBOV >
        # SMA-50. get_ibov_data devolve None em falha e ibov_in_uptrend(None,
        # ...) == True -> fail-OPEN por falta de dado MACRO (não trava o bot
        # por falta de um índice), comportamento idêntico ao backtest.
        ref_date = eng_df["ts"].iloc[-1]
        ibov_df = await asyncio.to_thread(get_ibov_data, eng_df["ts"].iloc[0])
        if not ibov_in_uptrend(ibov_df, ref_date):
            return self._hold(
                "Filtro macro: IBOV abaixo da SMA-50 — sem novas entradas.",
                last_price,
            )

        candidate = compute_signal(eng_df, self.ticker, **_signal_params())
        if candidate is None:
            return self._hold(
                "Sem sinal Donchian (breakout/SMA-200/volume/RSI não confirmados).",
                last_price,
            )

        # Candidate garante, por construção, stop < entry < target (breakout
        # de compra). score (0-1) vira 'confidence' só para exibição/log — o
        # dimensionamento NÃO usa mais confidence (ver risk_manager: sizing
        # alinhado ao backtest, Kelly fixo).
        return {
            "signal": "BUY",
            "confidence": min(100, max(1, round(candidate.score * 100))),
            "target_price": float(candidate.target),
            "stop_loss": float(candidate.stop),
            "reason": (
                f"Donchian breakout (diário): score {candidate.score:.2f}, "
                f"rompeu {candidate.signal_details.get('donchian_high')}, "
                f"RSI14 {candidate.rsi}, volume {candidate.volume_ratio}x, "
                f"stop {candidate.stop} / alvo {candidate.target} (ATR)."
            ),
            "last_price": float(candidate.entry_price),
        }
