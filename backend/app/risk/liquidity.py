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


def adtv_do_feed(df, janela: int = 21) -> Optional[float]:
    """Volume financeiro médio diário a partir do DataFrame que o feed JÁ traz.

    Deliberadamente não busca fonte nova: o feed ao vivo devolve OHLCV diário
    (`period="30d", interval="1d"`), e média de `close * volume` sobre a janela
    é tudo que o modelo de participação precisa. Exigir outro provedor viraria
    arquitetura nova para uma conta de uma linha.

    Devolve **None** quando não dá para calcular — e não 0.0. `None` é o sinal
    de "não sei", que em produção BLOQUEIA; `0.0` é um número, e números passam
    por comparações silenciosamente.
    """
    if df is None or len(df) == 0:
        return None
    cols = {c.lower(): c for c in df.columns}
    c_close = cols.get("close") or cols.get("c") or cols.get("adj_close")
    c_vol = cols.get("volume") or cols.get("v")
    if not c_close or not c_vol:
        return None
    try:
        fin = (df[c_close].astype(float) * df[c_vol].astype(float)).tail(janela)
    except (TypeError, ValueError):
        return None
    fin = fin[fin.notna()]
    if len(fin) == 0:
        return None
    media = float(fin.mean())
    return media if math.isfinite(media) and media > 0 else None


def max_participation_configurada() -> float:
    """Teto de participação no ADTV, vindo do settings.yaml.

    O valor (1%) saiu de MEDIÇÃO — é o platô da curva de capacidade, onde o
    excesso sobre o benchmark de mesmo risco se mantém em R$100k (ver
    BACKLOG). Fica em config, não hardcoded no laço de entradas, pela regra do
    CLAUDE.md: nunca número inventado quando já existe o equivalente
    configurado.
    """
    try:
        from trading_bot.core.config import AppConfig

        v = AppConfig.load().get("risk", "max_adtv_participation", default=0.01)
        v = float(v)
        return v if 0.0 < v <= 0.05 else 0.01
    except Exception:  # pragma: no cover — config ausente/inválida
        return 0.01
