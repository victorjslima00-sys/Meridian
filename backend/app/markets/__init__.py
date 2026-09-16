"""
Camada de Mercado/Corretora (Fase 1, Commit 1, Hardening NEXUS-004).

Ponto de entrada único: `get_market(nome)` e `get_broker(nome)`. O laço
de trading fala com estas fábricas, não com yfinance/ExecutorAgent
direto — é isso que torna um mercado novo (cripto) uma implementação
nova em vez de uma cirurgia no laço.

Exporta também os contratos de fase de sessão (B3SessionPhase) e calendário oficial.
"""
from __future__ import annotations

import re

from .b3 import B3Market
from .b3_session import (
    B3_CALENDAR_SOURCE,
    B3_CALENDAR_YEAR,
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
    get_b3_day_type,
    get_b3_session_phase,
)
from .base import Broker, Market
from .paper_broker import PaperBroker

# Instâncias únicas
_MARKETS: dict[str, Market] = {}
_BROKERS: dict[str, Broker] = {}


def get_market(name: str = "b3") -> Market:
    chave = (name or "").strip().lower()
    if chave not in ("b3",):
        raise ValueError(
            f"Mercado desconhecido: {name!r}. Disponíveis: ['b3']. "
            "Um mercado novo precisa de uma implementação de Market "
            "registrada aqui (ver BACKLOG.md)."
        )
    if chave not in _MARKETS:
        _MARKETS[chave] = B3Market()
    return _MARKETS[chave]


_B3_TICKER = re.compile(r"[A-Z]{4}\d{1,2}$")


def resolve_market(symbol: str) -> Market:
    """Descobre a QUE mercado um ticker TRADEÁVEL pertence."""
    s = (symbol or "").strip().upper()
    if s.endswith(".SA") or _B3_TICKER.fullmatch(s):
        return get_market("b3")
    raise ValueError(
        f"Não foi possível resolver o mercado do ticker {symbol!r}. "
        "Só a B3 está registrada (tickers .SA ou padrão AAAA9). Um ticker "
        "sem sufixo (ex.: cripto BTC-USD) exige resolução EXPLÍCITA por "
        "config — ver BACKLOG.md. NÃO assumir B3 por default."
    )


def get_broker(name: str = "paper") -> Broker:
    chave = (name or "").strip().lower()
    if chave not in ("paper",):
        raise ValueError(
            f"Corretora desconhecida: {name!r}. Disponíveis: ['paper']. "
            "PAPER TRADING é o único modo suportado (ver CLAUDE.md)."
        )
    if chave not in _BROKERS:
        _BROKERS[chave] = PaperBroker()
    return _BROKERS[chave]


__all__ = [
    "Market",
    "Broker",
    "get_market",
    "get_broker",
    "resolve_market",
    "B3Market",
    "PaperBroker",
    "B3SessionPhase",
    "B3DayType",
    "get_session_phase",
    "get_day_type",
    "get_b3_session_phase",
    "get_b3_day_type",
    "can_enter_new_position",
    "can_manage_exits",
    "B3_TIMEZONE",
    "B3_TIMEZONE_STR",
    "B3_SCHEDULE_SOURCE",
    "B3_SCHEDULE_EFFECTIVE_DATE",
    "B3_CALENDAR_SOURCE",
    "B3_CALENDAR_YEAR",
]
