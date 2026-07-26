"""
Caixa ocioso deve render a taxa livre de risco (CDI), não zero.

O backtest mantinha `capital_cash` (o dinheiro FORA de posições) parado: em
42% dos pregões não há posição aberta e, com kelly 0,25 / 3 slots, o teto de
exposição é 25% — ou seja ~66% do patrimônio fica em caixa, em média, rendendo
ZERO no modelo. Na vida real esse caixa estaria no CDI.

Isso distorcia a comparação central do projeto: "estratégia 5,36% vs CDI
10,08%" comparava 100%-no-CDI contra 34%-em-ações-e-66%-embaixo-do-colchão,
alternativas que ninguém escolheria. A correção credita a taxa diária sobre
`capital_cash` — só o caixa ocioso, nunca o capital investido (que vive em
`pos.capital`, fora de `capital_cash`).
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from trading_bot.backtest.engine import run_regime_backtest


def _serie_plana(n=280, preco=100.0) -> pd.DataFrame:
    """Série sem rompimento algum: preço constante, volume constante. Garante
    ZERO trades, isolando o efeito do rendimento do caixa na curva."""
    ts = pd.date_range("2022-01-01", periods=n, freq="D").date
    return pd.DataFrame({
        "ts": ts,
        "o": [preco] * n, "h": [preco] * n, "l": [preco] * n,
        "c": [preco] * n, "adj_close": [preco] * n, "v": [1000] * n,
    })


@pytest.fixture
def dados():
    return {"PLANO3.SA": _serie_plana()}


@pytest.fixture
def janela(dados):
    ts = dados["PLANO3.SA"]["ts"]
    return ts.iloc[-40], ts.iloc[-1]


def _roda(dados, janela, **kw):
    inicio, fim = janela
    return run_regime_backtest(
        data=dados, regime_name="caixa", start=inicio, end=fim,
        capital=1000.0, ibov_filter=False, warmup_bars=300, **kw,
    )


class TestCaixaOciosoRendeCDI:
    def test_sem_yield_o_caixa_fica_parado(self, dados, janela):
        """Baseline explícito: sem a série, o caixa não rende — a curva de um
        cenário sem trades é plana em 1000."""
        r = _roda(dados, janela)
        assert r.trades == []
        assert r.equity_curve[-1] == pytest.approx(1000.0)

    def test_caixa_ocioso_compoe_a_taxa_diaria(self, dados, janela):
        """Cenário sem trades: 100% do capital é caixa e deve compor exatamente
        a taxa diária. Com n dias a taxa fixa r, final = 1000*(1+r)^n."""
        inicio, fim = janela
        dias = [d for d in dados["PLANO3.SA"]["ts"] if inicio <= d <= fim]
        r_diaria = 0.0004  # ~10,6% a.a., ordem de grandeza do CDI
        serie = {d: r_diaria for d in dias}

        r = _roda(dados, janela, cash_daily_yield=serie)
        assert r.trades == []
        esperado = 1000.0 * (1 + r_diaria) ** len(dias)
        assert r.equity_curve[-1] == pytest.approx(esperado, rel=1e-9)

    def test_dia_sem_taxa_na_serie_nao_credita(self, dados, janela):
        """Robustez: data ausente da série (feriado, buraco) credita 0 naquele
        dia, não quebra nem inventa taxa."""
        inicio, fim = janela
        dias = [d for d in dados["PLANO3.SA"]["ts"] if inicio <= d <= fim]
        serie = {d: 0.0004 for d in dias[:-5]}  # últimos 5 dias faltando

        r = _roda(dados, janela, cash_daily_yield=serie)
        esperado = 1000.0 * (1 + 0.0004) ** (len(dias) - 5)
        assert r.equity_curve[-1] == pytest.approx(esperado, rel=1e-9)

    def test_yield_vazio_equivale_a_sem_yield(self, dados, janela):
        """Série vazia = nenhum rendimento, idêntico a não passar nada.
        Guarda contra a série virar caminho de código divergente."""
        base = _roda(dados, janela)
        vazio = _roda(dados, janela, cash_daily_yield={})
        assert base.equity_curve[-1] == pytest.approx(vazio.equity_curve[-1])
