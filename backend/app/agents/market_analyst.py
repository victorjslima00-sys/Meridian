"""
MarketAnalyst — gerador de sinal de ENTRADA (Fase 1, Commit 2, Hardening NEXUS-004).

MUDANÇA ESTRUTURAL: o sinal volta a ser a estratégia DETERMINÍSTICA que
foi backtestada — Donchian breakout de 20 dias + filtro estrutural
SMA-200 + confirmação de volume + RSI, com stop/alvo por ATR, no
timeframe DIÁRIO, e filtro macro IBOV (> SMA-50). É exatamente
`trading_bot/signals/engine.py::compute_signal`, com os MESMOS parâmetros
que o backtest lê (config/settings.yaml::signals).

NEXUS-004 HARDENING:
- Configuração fail-closed: sem fallbacks silenciosos se config estiver corrompida/ausente.
- Barras estritamente fechadas: a barra em formação do dia corrente é excluída.
- Filtro IBOV fail-closed: sem autorização de entrada se IBOV ausente, insuficiente ou <= SMA-50.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import date, datetime, time, timezone
from typing import Any, Dict, Optional, Union

from trading_bot.data import approval
from trading_bot.data.closed_frame import closed_daily_signal_frame
from trading_bot.signals.strategy_identity import get_active_strategy_id

from ..markets import resolve_market
from trading_bot.signals.engine import (
    compute_signal,
    get_ibov_data,
    ibov_in_uptrend,
)

logger = logging.getLogger(__name__)

# Mínimo de barras diárias fechadas: SMA-200 exige 200 de histórico + a barra de decisão.
_MIN_DAILY_BARS = 201


def _signal_params(settings_path: Any = None) -> Dict[str, Any]:
    """Parâmetros de PRODUÇÃO — a MESMA fonte que o backtest lê
    (config/settings.yaml::signals).
    
    FAIL-CLOSED (NEXUS-004): Sem fallbacks silenciosos. Se a configuração
    estiver ausente, corrompida ou contiver parâmetros não-finitos/inválidos,
    lança ValueError.
    """
    from trading_bot.core.config import AppConfig

    if settings_path is not None:
        cfg = AppConfig.load(settings_path=str(settings_path))
    else:
        cfg = AppConfig.load()

    sig = cfg.get("signals")
    if sig is None or not isinstance(sig, dict) or not sig:
        raise ValueError("Seção 'signals' ausente ou inválida nas configurações (fail-closed)")

    vol = sig.get("volume_multiplier", sig.get("volume_mult"))

    params = {
        "breakout_period": sig.get("breakout_period"),
        "volume_mult": vol,
        "sma_trend_period": sig.get("sma_trend_period"),
        "rsi_max": sig.get("rsi_max"),
        "stop_atr_mult": sig.get("stop_atr_mult"),
        "stop_pct": sig.get("stop_pct"),
        "target_atr_mult": sig.get("target_atr_mult"),
    }

    for k, v in params.items():
        if v is None:
            raise ValueError(f"Parâmetro obrigatório '{k}' ausente na configuração 'signals'")
        if isinstance(v, bool):
            raise ValueError(f"Parâmetro '{k}' não pode ser booleano: {v}")
        try:
            vf = float(v)
            if not math.isfinite(vf) or vf <= 0.0:
                raise ValueError(f"Parâmetro '{k}' deve ser finito e > 0: {v}")
        except (TypeError, ValueError) as err:
            raise ValueError(f"Parâmetro '{k}' numérico inválido: {v}") from err

    return {
        "breakout_period": int(params["breakout_period"]),
        "volume_mult": float(params["volume_mult"]),
        "sma_trend_period": int(params["sma_trend_period"]),
        "rsi_max": float(params["rsi_max"]),
        "stop_atr_mult": float(params["stop_atr_mult"]),
        "stop_pct": float(params["stop_pct"]),
        "target_atr_mult": float(params["target_atr_mult"]),
    }


class MarketAnalyst:
    _signal_params = staticmethod(_signal_params)

    def __init__(self, ticker: str):
        self.ticker = ticker

    def _hold(
        self,
        reason: str,
        last_price: float = 0.0,
        strategy_id: str = "donchian_breakout",
        market_date: Optional[str] = None,
        decision_bar_date: Optional[str] = None,
        today_bar_removed: bool = False,
        session_phase: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "signal": "HOLD",
            "side": "HOLD",
            "confidence": 0,
            "price": float(last_price) if last_price > 0 else 1.0,
            "target_price": 0.0,
            "stop_loss": 0.0,
            "reason": reason,
            "last_price": float(last_price),
            "generated_at": datetime.now(timezone.utc),
            "dataset_sha256": None,
            "dataset_approved": False,
            "strategy_id": strategy_id,
            "market_date": market_date,
            "decision_bar_date": decision_bar_date,
            "today_bar_removed": today_bar_removed,
            "session_phase": session_phase,
        }

    async def analyze(
        self,
        registry_path: Any = None,
        project_root: Any = None,
        settings_path: Any = None,
        as_of: Optional[Union[datetime, date]] = None,
    ) -> Dict[str, Any]:
        """Devolve o sinal do ticker: BUY (com alvo/stop por ATR) ou HOLD."""
        market = resolve_market(self.ticker)

        df = await asyncio.to_thread(
            market.fetch_ohlcv, self.ticker, period="2y", interval="1d"
        )
        return await self.analyze_ohlcv(
            df,
            registry_path=registry_path,
            project_root=project_root,
            settings_path=settings_path,
            as_of=as_of,
        )

    async def analyze_ohlcv(
        self,
        df: Any,
        registry_path: Any = None,
        project_root: Any = None,
        settings_path: Any = None,
        as_of: Optional[Union[datetime, date]] = None,
    ) -> Dict[str, Any]:
        """Deterministic analysis of pre-supplied OHLCV dataframe.
        Never refetches.
        """
        try:
            active_strategy = get_active_strategy_id(
                settings_path=settings_path
            )
        except Exception as exc:
            return self._hold(
                f"Estratégia ativa inválida ou não suportada: {exc}",
                0.0,
            )

        # 0. Parâmetros de estratégia fail-closed (NEXUS-004)
        try:
            params = _signal_params(settings_path=settings_path)
        except Exception as exc:
            return self._hold(
                f"Configuração de estratégia ausente ou inválida ({exc}) — fail-closed.",
                0.0,
                strategy_id=active_strategy,
            )

        # 1. Transformação de barras estritamente FECHADAS (NEXUS-004)
        as_of_dt = as_of
        if isinstance(as_of, date) and not isinstance(as_of, datetime):
            from backend.app.markets.b3_session import B3_TIMEZONE
            as_of_dt = datetime.combine(as_of, time(12, 0), tzinfo=B3_TIMEZONE)
        closed_res = closed_daily_signal_frame(df, as_of=as_of_dt, ticker=self.ticker)
        closed_df = closed_res.df
        mkt_date_str = str(closed_res.market_date)
        dec_bar_str = str(closed_res.decision_bar_date) if closed_res.decision_bar_date else None
        phase_str = closed_res.session_phase.value

        if closed_df is None or len(closed_df) < _MIN_DAILY_BARS:
            return self._hold(
                f"Dados diários insuficientes para o sinal Donchian (obtido {len(closed_df) if closed_df is not None else 0}, mínimo {_MIN_DAILY_BARS}).",
                0.0,
                strategy_id=active_strategy,
                market_date=mkt_date_str,
                decision_bar_date=dec_bar_str,
                today_bar_removed=closed_res.today_bar_removed,
                session_phase=phase_str,
            )

        last_price = float(closed_df["close"].iloc[-1])

        # Adapta o schema do feed (date/open/high/low/close/volume) para o engine
        try:
            eng_df = approval.normalize_ohlcv_to_signal_df(closed_df)
        except Exception as exc:
            return self._hold(
                f"Falha na normalização dos dados diários: {exc}",
                last_price,
                strategy_id=active_strategy,
                market_date=mkt_date_str,
                decision_bar_date=dec_bar_str,
                today_bar_removed=closed_res.today_bar_removed,
                session_phase=phase_str,
            )

        # Filtro macro IBOV (NEXUS-004 fail-closed)
        ref_date = closed_res.decision_bar_date
        ibov_df = await asyncio.to_thread(get_ibov_data, eng_df["ts"].iloc[0])
        if not ibov_in_uptrend(ibov_df, ref_date, current_market_date=closed_res.market_date):
            return self._hold(
                "Filtro macro: IBOV indisponível, insuficiente ou abaixo da SMA-50 — sem novas entradas.",
                last_price,
                strategy_id=active_strategy,
                market_date=mkt_date_str,
                decision_bar_date=dec_bar_str,
                today_bar_removed=closed_res.today_bar_removed,
                session_phase=phase_str,
            )

        candidate = compute_signal(
            eng_df,
            self.ticker,
            registry_path=registry_path,
            project_root=project_root,
            settings_path=settings_path,
            **params,
        )
        if candidate is None:
            return self._hold(
                "Sem sinal Donchian (breakout/SMA-200/volume/RSI não confirmados).",
                last_price,
                strategy_id=active_strategy,
                market_date=mkt_date_str,
                decision_bar_date=dec_bar_str,
                today_bar_removed=closed_res.today_bar_removed,
                session_phase=phase_str,
            )

        try:
            d_sha = approval.dataset_digest(eng_df, self.ticker)
            authority = approval.require_dataset_approval_by_digest(
                d_sha,
                registry_path=registry_path,
                project_root=project_root,
                settings_path=settings_path,
            )
            if (authority.dataset_sha256 != d_sha or authority.ticker != self.ticker
                    or authority.strategy_id != active_strategy
                    or authority.intended_use != "PAPER_TRADING" or authority.status != "approved"):
                raise ValueError("Approval identity mismatch for ticker/strategy/dataset/scope")
        except Exception as e:
            logger.warning(
                "MarketAnalyst dataset approval check failed for %s: %s",
                self.ticker,
                e,
            )
            return self._hold(
                f"Aprovação de dados ausente ou inválida ({e}) — entrada bloqueada (fail-closed).",
                last_price,
                strategy_id=active_strategy,
                market_date=mkt_date_str,
                decision_bar_date=dec_bar_str,
                today_bar_removed=closed_res.today_bar_removed,
                session_phase=phase_str,
            )

        return {
            "ticker": self.ticker,
            "signal": "BUY",
            "side": "BUY",
            "price": float(candidate.entry_price),
            "last_price": float(candidate.entry_price),
            "confidence": min(100, max(1, round(candidate.score * 100))),
            "target_price": float(candidate.target),
            "stop_loss": float(candidate.stop),
            "reason": (
                f"Donchian breakout (diário): score {candidate.score:.2f}, "
                f"rompeu {candidate.signal_details.get('donchian_high')}, "
                f"RSI14 {candidate.rsi}, volume {candidate.volume_ratio}x, "
                f"stop {candidate.stop} / alvo {candidate.target} (ATR)."
            ),
            "generated_at": datetime.now(timezone.utc),
            "dataset_sha256": authority.dataset_sha256,
            "dataset_approved": True,
            "strategy_id": authority.strategy_id,
            "candidate_id": authority.candidate_id,
            "intended_use": authority.intended_use,
            "market_date": mkt_date_str,
            "decision_bar_date": dec_bar_str,
            "today_bar_removed": closed_res.today_bar_removed,
            "session_phase": phase_str,
        }
