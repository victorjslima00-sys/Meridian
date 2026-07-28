"""Portão de liquidez em PRODUÇÃO — fail-CLOSED.

Assimetria deliberada em relação ao backtest. O MESMO dado ausente significa
coisas diferentes nos dois contextos:

  BACKTEST  ausência de ADTV = LACUNA HISTÓRICA. O papel não tinha volume
            registrado naquele pregão de 2013. Bloquear a entrada apagaria
            trades por falta de dado e não por iliquidez, enviesando a
            medição — por isso `run_regime_backtest` usa fail-SAFE.

  PRODUÇÃO  ausência de ADTV = FEED DEGRADADO AGORA. O provedor pode estar
            fora do ar, com rate limit, ou devolvendo campo vazio. Entrar sem
            saber a liquidez é exatamente o cenário que o teto de participação
            existe para evitar. Vale a regra geral do CLAUDE.md: dado não
            confiável = não age.

Escopo: só ENTRADAS. A gestão de saídas não passa por aqui — bloquear saída
por falta de dado prenderia capital em risco, que é o oposto de fail-closed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LiquidityDecision:
    aprovado: bool
    motivo: str = ""
    participacao: Optional[float] = None


def avaliar_liquidez_para_entrada(
    ticker: str,
    order_value: float,
    adtv_brl: Optional[float],
    max_participation: float,
) -> LiquidityDecision:
    """Decide se uma ENTRADA pode ser executada dada a liquidez do papel.

    `max_participation=0` desliga o TETO, não a exigência de dado: se desligar
    o teto também desligasse a checagem de disponibilidade, um erro de config
    reabriria a porta em silêncio.
    """
    if adtv_brl is None or not math.isfinite(adtv_brl) or adtv_brl <= 0:
        return LiquidityDecision(
            aprovado=False,
            motivo=(
                f"liquidez indisponivel para {ticker} (ADTV={adtv_brl!r}) — "
                "fail-closed: feed degradado nao autoriza entrada as cegas"
            ),
        )

    participacao = order_value / adtv_brl
    if max_participation > 0 and participacao > max_participation:
        return LiquidityDecision(
            aprovado=False,
            participacao=participacao,
            motivo=(
                f"participacao {participacao:.2%} do ADTV de {ticker} excede o "
                f"teto de {max_participation:.2%}"
            ),
        )
    return LiquidityDecision(aprovado=True, participacao=participacao)
