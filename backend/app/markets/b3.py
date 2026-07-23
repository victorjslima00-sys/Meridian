"""
B3 — implementação de Market (Fase 1, Commit 1).

REFATORAÇÃO PURA: cada método DELEGA para o código que já roda em
produção (backend/app/data/feed.py, database.hoje_b3). Nenhuma regra de
trading nasce aqui. Isso é o que sustenta a promessa de "zero mudança de
comportamento" deste commit.

A delegação é feita por ATRIBUTO DE MÓDULO (`feed.fetch_recent_data(...)`,
não `from ...feed import fetch_recent_data`) de propósito: os testes que
já existem monkeypatcham `backend.app.data.feed.fetch_recent_data` e
`...get_current_price`, e a busca do atributo em tempo de chamada faz
esses patches continuarem valendo através da abstração. Um `from ...
import` congelaria a referência no import e quebraria esses testes — e
um teste que para de exercer o caminho real é pior que nenhum teste.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from ..data import feed

logger = logging.getLogger(__name__)

# Fallbacks alinhados ao config/settings.yaml (scheduler). Só entram em
# ação se o YAML não puder ser lido — nunca "inventam" um pregão diferente
# do configurado.
_DEFAULT_TZ = "America/Sao_Paulo"
_DEFAULT_OPEN = "10:00"
_DEFAULT_CLOSE = "17:30"


def _hhmm(valor: str, fallback: str) -> datetime.time:
    try:
        h, m = str(valor).split(":")
        return datetime.time(int(h), int(m))
    except Exception:
        h, m = fallback.split(":")
        return datetime.time(int(h), int(m))


class B3Market:
    """Bolsa brasileira via yfinance (sufixo .SA), fuso de Brasília."""

    name = "b3"

    def __init__(self) -> None:
        sched: dict[str, Any] = {}
        try:
            from trading_bot.core.config import AppConfig

            sched = AppConfig.load().get("scheduler", default={}) or {}
        except Exception as exc:  # config ausente/ilegível não derruba o app
            logger.warning("scheduler do settings.yaml indisponível (%s); usando padrões B3", exc)

        self.timezone = ZoneInfo(sched.get("timezone", _DEFAULT_TZ))
        self._open = _hhmm(sched.get("market_open", _DEFAULT_OPEN), _DEFAULT_OPEN)
        self._close = _hhmm(sched.get("market_close", _DEFAULT_CLOSE), _DEFAULT_CLOSE)

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

    # --- calendário -------------------------------------------------------

    def today(self) -> datetime.date:
        return datetime.datetime.now(self.timezone).date()

    def is_open(self, now: Optional[datetime.datetime] = None) -> bool:
        """Pregão regular: dia útil, entre market_open e market_close
        (limites inclusivos), no fuso do mercado.

        NÃO considera feriados da B3 (exigiria calendário externo) — está
        registrado no BACKLOG. E, importante: este método NÃO é chamado
        pelo laço de trading neste commit. Ligá-lo mudaria comportamento
        (hoje o bot opera fora do pregão), e este commit é refatoração de
        comportamento zero. Fica disponível para uma decisão explícita.
        """
        agora = now or datetime.datetime.now(self.timezone)
        if agora.tzinfo is None:
            agora = agora.replace(tzinfo=self.timezone)
        else:
            agora = agora.astimezone(self.timezone)

        if agora.weekday() >= 5:  # 5=sábado, 6=domingo
            return False
        return self._open <= agora.time() <= self._close
