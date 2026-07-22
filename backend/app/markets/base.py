"""
Protocolos de Mercado e Corretora (Fase 1, Commit 1).

Por que protocolos (structural typing) e não classes-base abstratas: as
implementações que já existem (o feed do yfinance, o ExecutorAgent) não
foram escritas para herdar de nada. Protocol deixa adaptá-las por
composição, sem tocar na hierarquia delas — e `runtime_checkable`
permite o teste provar conformidade sem acoplar.

ESCOPO DELIBERADAMENTE MÍNIMO: só entram aqui os métodos que o laço de
trading REALMENTE usa hoje. Interface especulativa ("e se um dia
precisarmos de order book?") é dívida disfarçada de previdência — o
encaixe para um mercado novo é o que está aqui, e ele cresce quando o
segundo mercado existir de verdade e mostrar o que falta.
"""
from __future__ import annotations

import datetime
from typing import Any, Optional, Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class Market(Protocol):
    """Tudo que é específico de UM mercado: como se chama um símbolo, de
    onde vem o preço, que dias/horas ele opera, qual é o universo."""

    name: str

    def normalize_symbol(self, ticker: str) -> str:
        """Forma canônica do símbolo para o feed deste mercado
        (ex.: PETR4 -> PETR4.SA na B3)."""
        ...

    def symbols(self) -> list[str]:
        """Universo operável, já normalizado."""
        ...

    def fetch_ohlcv(
        self,
        ticker: str,
        period: str = "5d",
        interval: str = "1h",
        ttl: Optional[float] = None,
    ) -> Optional[pd.DataFrame]:
        """OHLCV recente. None quando não há dado confiável — o chamador
        trata como fail-closed, nunca fabrica preço."""
        ...

    def current_price(self, ticker: str) -> float:
        """Último preço; 0.0 em falha (mesma convenção do feed atual)."""
        ...

    def today(self) -> datetime.date:
        """Data corrente no fuso do mercado."""
        ...

    def is_open(self, now: Optional[datetime.datetime] = None) -> bool:
        """Se o mercado está em pregão neste instante."""
        ...


@runtime_checkable
class Broker(Protocol):
    """Execução. Hoje só existe o simulador de paper trading; a interface
    é a mesma que uma corretora real (Cedro) precisaria implementar."""

    name: str

    def execute_order(
        self, ticker: str, decision: dict[str, Any], analysis: dict[str, Any]
    ) -> dict[str, Any]:
        ...

    def close_order(
        self, trade_id: int, current_price: float, reason: str
    ) -> dict[str, Any]:
        ...
