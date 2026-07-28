"""Filtro de sanidade de OHLCV — descarta o PREGÃO implausível, não o período.

A auditoria de 2026-07-27 mostrou que o yfinance serve, para tickers da B3,
dois defeitos objetivos e sem nenhum aviso da fonte:

  volume financeiro implausível  11,6% dos pregões abaixo de R$100k/dia
                                 (PCAR3, blue chip, com 3 ações/dia em 2008)
  fechamento congelado            4,78% do total; UGPA3 fica 590 pregões
                                 fixo em R$3.302.501,25

O dilema aparente era escolher entre 15 anos de dado sujo e 7 anos limpos.
Este módulo é a terceira via: remover a barra ruim e **manter a janela**. Uma
barra descartada vira ausência de dado — o indicador não a vê — e isso é mais
honesto que propagar um número inventado.

O que este filtro deliberadamente NÃO faz: cortar por retorno extremo. Queda
de 50% num dia existe de verdade (limite, crise, fraude revelada), e removê-la
apagaria justamente os eventos que a estratégia precisa aguentar — enviesando
o backtest para cima. Os dois critérios acima são objetivos e verificáveis;
"retorno grande demais" é julgamento disfarçado de saneamento.
"""
from __future__ import annotations

from typing import Optional, Union

import numpy as np
import pandas as pd

# Nenhum papel do universo (IBrA/blue chips) negocia menos que isto de verdade.
MIN_FINANCIAL_VOLUME_BRL = 100_000.0

# Nenhum papel real fecha no MESMO centavo por 5 pregões seguidos. Runs de 2-3
# acontecem em pregão fraco e são preservados de propósito.
MAX_FROZEN_RUN = 4


def _frozen_mask(close: np.ndarray, max_run: int) -> np.ndarray:
    """True nas barras que pertencem a um bloco de fechamentos idênticos com
    comprimento > `max_run`. Marca o bloco INTEIRO (inclusive a primeira
    barra), porque numa série remontada nenhuma delas é observação real."""
    n = len(close)
    ruim = np.zeros(n, dtype=bool)
    if n < 2:
        return ruim
    ini = 0
    for i in range(1, n + 1):
        if i < n and close[i] == close[ini]:
            continue
        if (i - ini) > max_run:
            ruim[ini:i] = True
        ini = i
    return ruim


def sanitize_ohlcv(
    df: pd.DataFrame,
    min_financial_volume: float = MIN_FINANCIAL_VOLUME_BRL,
    max_frozen_run: int = MAX_FROZEN_RUN,
    return_report: bool = False,
) -> Union[pd.DataFrame, tuple[pd.DataFrame, dict]]:
    """Remove pregões implausíveis de um OHLCV (schema ts/o/h/l/c/adj_close/v).

    Retorna o DataFrame saneado; com `return_report=True`, também um dicionário
    com a contagem de descartes por motivo — descarte silencioso seria o mesmo
    pecado do dado silenciosamente errado.
    """
    relatorio = {
        "total_entrada": len(df),
        "descartados_volume": 0,
        "descartados_congelamento": 0,
        "total_saida": len(df),
    }
    if df is None or len(df) == 0:
        return (df, relatorio) if return_report else df

    # Um saneador NUNCA pode derrubar o pipeline: schema incompleto degrada
    # para o critério que ainda dá para aplicar, em vez de estourar. Fontes
    # diferentes (e mocks de teste) nem sempre trazem volume.
    if "c" not in df.columns:
        return (df, relatorio) if return_report else df

    d = df.sort_values("ts").reset_index(drop=True)
    close = d["c"].to_numpy(dtype=float)

    if "v" in d.columns:
        financeiro = close * d["v"].to_numpy(dtype=float)
        ruim_vol = np.isfinite(financeiro) & (financeiro < min_financial_volume)
    else:
        ruim_vol = np.zeros(len(close), dtype=bool)

    ruim_congelado = _frozen_mask(close, max_frozen_run)

    relatorio["descartados_volume"] = int(ruim_vol.sum())
    relatorio["descartados_congelamento"] = int((ruim_congelado & ~ruim_vol).sum())

    out = d.loc[~(ruim_vol | ruim_congelado)].reset_index(drop=True)
    relatorio["total_saida"] = len(out)
    return (out, relatorio) if return_report else out


def sanitize_universe(
    data: dict[str, pd.DataFrame],
    min_financial_volume: float = MIN_FINANCIAL_VOLUME_BRL,
    max_frozen_run: int = MAX_FROZEN_RUN,
) -> tuple[dict[str, pd.DataFrame], dict]:
    """Aplica `sanitize_ohlcv` a um universo inteiro e agrega o relatório."""
    saneado: dict[str, pd.DataFrame] = {}
    agregado = {
        "total_entrada": 0, "descartados_volume": 0,
        "descartados_congelamento": 0, "total_saida": 0, "por_ticker": {},
    }
    for tk, df in data.items():
        if df is None or len(df) == 0:
            continue
        out, rel = sanitize_ohlcv(df, min_financial_volume, max_frozen_run, True)
        saneado[tk] = out
        for k in ("total_entrada", "descartados_volume",
                  "descartados_congelamento", "total_saida"):
            agregado[k] += rel[k]
        agregado["por_ticker"][tk] = rel
    return saneado, agregado
