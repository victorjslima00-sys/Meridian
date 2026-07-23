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

import re

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


# Forma de ticker da B3: sufixo .SA (após normalização) OU o padrão cru
# AAAA9/AAAA99 (PETR4, VALE3, SANB11, BBSE3). Cobre o universo B3; NÃO
# casa cripto (BTC-USD tem hífen e "USD"), índices (^BVSP) nem ETFs
# estrangeiros (SPY).
_B3_TICKER = re.compile(r"[A-Z]{4}\d{1,2}$")


def resolve_market(symbol: str) -> Market:
    """Descobre a QUE mercado um ticker TRADEÁVEL pertence.

    ⚠️ ESTRATÉGIA ATUAL — mapeamento por FORMA/sufixo do ticker. É
    pragmática e deliberada: só a B3 existe hoje, então não vale construir
    o registry de cripto antes de cripto existir. MAS esta função é o ponto
    onde o "conserto rápido" errado vai tentar entrar no futuro.

    QUANDO CRIPTO ENTRAR, a forma CERTA de estender é resolução EXPLÍCITA:
    o mercado de cada ticker declarado em CONFIG (ex.: um mapa
    ticker→mercado, ou por padrão/prefixo registrado), NUNCA um `if
    symbol in {"BTC-USD", "ETH-USD"}` hardcoded aqui. Símbolo hardcoded é
    exatamente o bug que só aparece quando o segundo mercado chega.

    FAIL-CLOSED (condição travada pelo usuário): um ticker que não casa
    nenhum mercado conhecido levanta ValueError — NUNCA cai em B3 por
    default. Um ticker de cripto virando silenciosamente ação seria a
    classe de bug que só se manifesta em produção com dinheiro (mesmo
    espírito da proibição de defaults inseguros no CLAUDE.md).

    Fora de escopo: símbolos de DADO, não de trade (^BVSP para o filtro
    macro, câmbio) — não são instrumentos operáveis e não passam por aqui.
    """
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
]
