"""
Regressão: o backtest por regime descartava os primeiros 200 pregões de CADA
janela.

`run_regime_backtest` cortava o DataFrame PARA a janela do regime ANTES de
calcular indicadores (engine.py:132) e depois exigia `len(df_hist) >= 200`
para a SMA-200 (engine.py:241). Consequência medida nos regimes reais:

    crise_volatilidade  148 pregões ->   0 testáveis (0%)   <-- n=0 era ARTEFATO
    alta_juros          396 pregões -> 196 testáveis (49%)
    recuperacao_lateral 372 pregões -> 172 testáveis (46%)

Ou seja: a janela de crise era estruturalmente incapaz de gerar sinal, e o
`n=0 trades` foi registrado como se fosse prova de que o filtro de tendência
bloqueou as entradas. Não era — o backtest nunca chegou a rodar ali.

A correção mantém um buffer de barras ANTERIORES ao `start` só para alimentar
os indicadores, sem permitir entradas fora da janela.
"""
import numpy as np
import pandas as pd
import pytest

from trading_bot.backtest.engine import run_regime_backtest


N_TOTAL = 460
N_JANELA = 60
I_BREAKOUT = 430  # dentro da janela; entrada acontece na barra seguinte


def _serie_com_breakout_na_janela() -> pd.DataFrame:
    """Série diária longa (schema do backtest: ts/o/h/l/c/v/adj_close).

    Tendência de alta suave com ruído — o mesmo processo já validado contra o
    `compute_signal` real em test_backend_agents.py (RSI ~68, abaixo do teto
    75). O rompimento Donchian é forçado em I_BREAKOUT, que cai DENTRO da
    janela do regime mas a menos de 200 barras do início dela: é exatamente o
    caso que o bug tornava invisível.
    """
    rng = np.random.default_rng(0)
    price = 85.0
    closes = []
    for _ in range(N_TOTAL):
        price += 0.015 + rng.normal(0, 0.35)
        closes.append(price)

    closes[I_BREAKOUT] = max(closes[I_BREAKOUT - 20:I_BREAKOUT]) * 1.02

    volumes = [1000] * N_TOTAL
    volumes[I_BREAKOUT] = 3000  # confirmação de volume (mult 1.5)

    return pd.DataFrame({
        "ts": pd.date_range("2022-01-01", periods=N_TOTAL, freq="D").date,
        "o": [c * 0.999 for c in closes],
        "h": [c * 1.006 for c in closes],
        "l": [c * 0.994 for c in closes],
        "c": closes,
        "adj_close": closes,
        "v": volumes,
    })


@pytest.fixture
def dados():
    return {"TESTE3.SA": _serie_com_breakout_na_janela()}


@pytest.fixture
def janela(dados):
    ts = dados["TESTE3.SA"]["ts"]
    return ts.iloc[N_TOTAL - N_JANELA], ts.iloc[N_TOTAL - 1]


def _roda(dados, janela, **kw):
    inicio, fim = janela
    return run_regime_backtest(
        data=dados,
        regime_name="janela_curta",
        start=inicio,
        end=fim,
        capital=300.0,
        ibov_filter=False,  # sem rede: o filtro macro não é o objeto do teste
        **kw,
    )


class TestWarmupDaJanela:
    def test_janela_menor_que_a_sma200_ainda_opera(self, dados, janela):
        """RED antes do fix: a janela tem 60 pregões, a SMA-200 precisa de 200,
        e o corte prévio dos dados tornava QUALQUER sinal impossível."""
        r = _roda(dados, janela)
        assert len(r.trades) > 0, (
            "Nenhum trade numa janela com breakout válido: o backtest está "
            "descartando os indicadores por cortar os dados antes de calculá-los."
        )

    def test_buffer_nao_permite_entrada_antes_do_inicio_do_regime(self, dados, janela):
        """O buffer é só história para indicador — não estende o período
        operado. Entrada fora da janela seria contaminar o regime medido."""
        inicio, fim = janela
        r = _roda(dados, janela)
        assert r.trades, "sem trades não há o que verificar"
        for t in r.trades:
            assert t.entry_date >= inicio, f"entrada em {t.entry_date}, antes de {inicio}"
            assert t.entry_date <= fim, f"entrada em {t.entry_date}, depois de {fim}"

    def test_curva_de_patrimonio_cobre_so_a_janela(self, dados, janela):
        """Um ponto de equity por pregão DA JANELA — o buffer não pode aparecer
        na curva, senão o Sharpe do regime é calculado sobre outro período."""
        r = _roda(dados, janela)
        assert len(r.equity_curve) == N_JANELA

    def test_ticker_sem_dados_na_janela_fica_de_fora(self, dados, janela):
        """O buffer não pode ressuscitar um ticker que não negociou na janela:
        30 barras mínimas continuam sendo exigidas DENTRO do período."""
        inicio, _ = janela
        df = dados["TESTE3.SA"]
        dados["CURTO3.SA"] = df[df["ts"] < inicio].copy()  # só passado, nada na janela
        r = _roda(dados, janela)
        assert all(t.ticker != "CURTO3.SA" for t in r.trades)
