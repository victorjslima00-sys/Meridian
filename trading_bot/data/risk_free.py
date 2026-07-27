"""Série de taxa livre de risco (CDI diário) — fonte de verdade única.

Antes, a série do CDI que a análise usava vivia num script de scratchpad e
se perdia entre sessões. Aqui ela é dado versionado do repositório
(`cdi_sgs12.csv`), extraído da API SGS do Banco Central, série 12 (CDI ao
dia, % a.d.).

Usos:
  - creditar juros sobre o caixa ocioso no backtest (`run_regime_backtest`);
  - derivar o risk-free real para o Sharpe do portão e do otimizador, em vez
    da constante mágica `RISK_FREE_RATE_ANNUAL`.
"""
from __future__ import annotations

import csv
from datetime import date
from functools import lru_cache
from pathlib import Path

_CSV = Path(__file__).with_name("cdi_sgs12.csv")


@lru_cache(maxsize=4)
def load_cdi_daily_fractions(path: str | None = None) -> dict[date, float]:
    """Retorna {data: taxa diária como FRAÇÃO}. Ex.: 0.0655% a.d. -> 0.000655.

    A fonte grava a taxa em PONTO PERCENTUAL ao dia (coluna rate_pct_day); a
    divisão por 100 aqui é a única conversão — quem consome recebe fração,
    pronta para `capital *= (1 + taxa)`.
    """
    p = Path(path) if path else _CSV
    out: dict[date, float] = {}
    with p.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[date.fromisoformat(row["date"])] = float(row["rate_pct_day"]) / 100.0
    return out


def cdi_annualized(fractions: dict[date, float] | None = None) -> float:
    """Taxa anual composta equivalente ao período coberto pela série.

    Deriva o risk-free do que a série realmente cobre, em vez de fixar um
    número. Serve para alimentar o Sharpe com um risk-free honesto quando o
    período do backtest for o mesmo da série.
    """
    fr = fractions if fractions is not None else load_cdi_daily_fractions()
    if not fr:
        return 0.0
    dias = sorted(fr)
    acum = 1.0
    for d in dias:
        acum *= 1 + fr[d]
    anos = max((dias[-1] - dias[0]).days / 365.25, 1e-9)
    return acum ** (1 / anos) - 1
