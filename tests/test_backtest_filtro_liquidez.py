"""
Filtro de liquidez: não abrir posição cuja ordem exceda X% do ADTV.

É **restrição de execução**, não otimização de sinal. Uma ordem que representa
50% do volume diário de um papel não é executável ao preço do backtest — a
premissa de "compro ao preço de abertura" quebra muito antes disso. Recusar a
entrada é modelar a realidade, não escolher trades vencedores.

Por isso é aplicado como filtro de ENTRADA (o candidato é descartado naquele
dia, com aquele tamanho de ordem) e nunca como exclusão retroativa de universo:
o mesmo papel volta a ser elegível quando o capital ou a liquidez mudarem.

A distinção importa para a honestidade do resultado. Um filtro retroativo
("nunca opere small caps") seria curve-fitting travestido; um filtro de entrada
dependente do tamanho da ordem é a mesma regra que um operador real enfrenta.
"""
from datetime import date

import pandas as pd
import pytest

from trading_bot.backtest.engine import run_regime_backtest
from tests.test_backtest_warmup import _serie_com_breakout_na_janela, N_TOTAL, N_JANELA


@pytest.fixture
def dados():
    return {"TESTE3.SA": _serie_com_breakout_na_janela()}


@pytest.fixture
def janela(dados):
    ts = dados["TESTE3.SA"]["ts"]
    return ts.iloc[N_TOTAL - N_JANELA], ts.iloc[N_TOTAL - 1]


def _adtv(dados, valor):
    ts = dados["TESTE3.SA"]["ts"]
    return {"TESTE3.SA": {d: valor for d in ts}}


def _roda(dados, janela, capital=300.0, **kw):
    inicio, fim = janela
    return run_regime_backtest(
        data=dados, regime_name="liq", start=inicio, end=fim,
        capital=capital, ibov_filter=False, warmup_bars=300, **kw,
    )


class TestFiltroDeLiquidez:
    def test_desligado_por_padrao(self, dados, janela):
        """Guarda de regressão: sem limite configurado, nada muda."""
        base = _roda(dados, janela)
        com = _roda(dados, janela, adtv_brl=_adtv(dados, 1e9), max_adtv_participation=0.0)
        assert [t.ticker for t in base.trades] == [t.ticker for t in com.trades]

    def test_bloqueia_entrada_quando_a_ordem_excede_o_limite(self, dados, janela):
        """ADTV minúsculo: qualquer ordem estoura o limite e nenhuma posição
        pode ser aberta."""
        r = _roda(dados, janela, adtv_brl=_adtv(dados, 100.0), max_adtv_participation=0.01)
        assert r.trades == []

    def test_permite_entrada_quando_ha_liquidez_de_sobra(self, dados, janela):
        """Contraprova: com ADTV grande o filtro não pode interferir."""
        base = _roda(dados, janela)
        com = _roda(dados, janela, adtv_brl=_adtv(dados, 1e9), max_adtv_participation=0.01)
        assert len(com.trades) == len(base.trades)
        assert len(com.trades) > 0

    def test_e_filtro_de_ENTRADA_dependente_do_tamanho_da_ordem(self, dados, janela):
        """O mesmo papel, o mesmo dia, o mesmo ADTV: passa com capital pequeno
        e é bloqueado com capital grande. Se o filtro fosse retroativo de
        universo, os dois casos dariam igual — e seria curve-fitting."""
        adtv = _adtv(dados, 50_000.0)
        kw = dict(adtv_brl=adtv, max_adtv_participation=0.01)   # teto = R$500
        pequeno = _roda(dados, janela, capital=300.0, **kw)     # ordem ~R$25
        grande = _roda(dados, janela, capital=300_000.0, **kw)  # ordem ~R$25k
        assert len(pequeno.trades) > 0
        assert grande.trades == []

    def test_sem_dado_de_adtv_nao_bloqueia(self, dados, janela):
        """Fail-safe: ausência de ADTV para o ticker-data não pode virar veto
        silencioso — isso apagaria trades por falta de dado, não por iliquidez."""
        base = _roda(dados, janela)
        r = _roda(dados, janela, adtv_brl={"OUTRO3.SA": {}}, max_adtv_participation=0.01)
        assert len(r.trades) == len(base.trades)
