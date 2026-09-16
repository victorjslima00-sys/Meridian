"""B3 — implementação de Market integrada ao B3SessionPhase e Calendário Oficial (NEXUS-004).

Utiliza o calendário oficial de 2026 (OC 003-2026-VNC) e a grade horária
vigente para ações (Circular 005/2026 PRE, a partir de 2026-03-09).
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from ..data import feed
from .b3_session import (
    B3_CALENDAR_SOURCE,
    B3_SCHEDULE_EFFECTIVE_DATE,
    B3_SCHEDULE_SOURCE,
    B3_TIMEZONE,
    B3_TIMEZONE_STR,
    B3DayType,
    B3SessionPhase,
    can_enter_new_position,
    can_manage_exits,
    get_day_type,
    get_session_phase,
)

logger = logging.getLogger(__name__)


class B3Market:
    """Bolsa brasileira via yfinance (sufixo .SA), fuso de Brasília e sessões oficiais."""

    name = "b3"

    def __init__(self) -> None:
        self.timezone = B3_TIMEZONE
        self.schedule_source = B3_SCHEDULE_SOURCE
        self.schedule_effective_date = B3_SCHEDULE_EFFECTIVE_DATE
        self.calendar_source = B3_CALENDAR_SOURCE

    # --- símbolos ---------------------------------------------------------

    def normalize_symbol(self, ticker: str) -> str:
        return feed._normalize_ticker(ticker)

    def symbols(self) -> list[str]:
        try:
            from trading_bot.core.config import AppConfig

            brutos = AppConfig.load().get("_universe", "tickers", default=[]) or []
        except Exception as exc:
            logger.warning("universo indisponível no settings.yaml (%s)", exc)
            brutos = []
        return [self.normalize_symbol(t) for t in brutos]

    # --- dados ------------------------------------------------------------

    def fetch_ohlcv(
        self,
        ticker: str,
        period: str = "5d",
        interval: str = "1h",
        ttl: Optional[float] = None,
    ) -> Optional[pd.DataFrame]:
        return feed.fetch_recent_data(ticker, period=period, interval=interval, ttl=ttl)

    def current_price(self, ticker: str) -> float:
        return feed.get_current_price(ticker)

    # --- calendário e sessões ---------------------------------------------

    def today(self) -> datetime.date:
        return datetime.datetime.now(self.timezone).date()

    def get_session_phase(self, now: Optional[datetime.datetime] = None) -> B3SessionPhase:
        """Retorna a fase atual da sessão da B3 segundo a Circular 005/2026 PRE."""
        return get_session_phase(now)

    def get_day_type(self, market_date: Optional[datetime.date] = None) -> B3DayType:
        """Classifica o dia de acordo com o calendário oficial da B3."""
        d = market_date or self.today()
        return get_day_type(d)

    def is_open(self, now: Optional[datetime.datetime] = None) -> bool:
        """Retorna True se o mercado está em fase CONTINUOUS (aberto para novas ordens).
        
        Substitui a semântica ingênua de dia de semana + 10:00-17:30 pela fase
        oficial CONTINUOUS da B3 (10:00-16:55 em dias normais).
        """
        return can_enter_new_position(now)

    def can_enter_new_position(self, now: Optional[datetime.datetime] = None) -> bool:
        """Novas entradas autônomas são permitidas ESTRITAMENTE em fase CONTINUOUS."""
        return can_enter_new_position(now)

    def can_manage_exits(self) -> bool:
        """Proteção de saída opera independentemente do fechamento de novas entradas."""
        return can_manage_exits()
