"""
Camada de Mercado/Corretora (Fase 1, Commit 1).

Ponto de entrada único: `get_market(nome)` e `get_broker(nome)`. O laço
de trading fala com estas fábricas, não com yfinance/ExecutorAgent
direto — é isso que torna um mercado novo (cripto) uma implementação
nova em vez de uma cirurgia no laço.

Hoje só existe B3 + paper. Adicionar cripto = criar `crypto.py` com um
Market (feed próprio, calendário 24/7, sem sufixo .SA) e registrá-lo em
_MARKETS. Ver BACKLOG.md para o que mais falta.

Fail-closed: pedir um mercado inexistente levanta ValueError. Cair para
a B3 silenciosamente faria um bot de cripto operar ações — exatamente o
tipo de "default conveniente" que a regra de segredos/defaults do
CLAUDE.md existe para proibir.
"""
from __future__ import annotations

from .b3 import B3Market
from .base import Broker, Market
from .paper_broker import PaperBroker

# Instâncias únicas: são objetos sem estado mutável (só configuração lida
# no init), então compartilhá-las evita reler o YAML a cada chamada.
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


__all__ = ["Market", "Broker", "get_market", "get_broker", "B3Market", "PaperBroker"]
