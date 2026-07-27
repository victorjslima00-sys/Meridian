"""
Impacto de mercado (slippage por participação no volume).

Até aqui o custo era fração FIXA da posição (`brokerage_pct`, `spread_pct`)
mais taxa fixa por ordem. Nenhum termo escalava com a **liquidez do ativo**.
Em R$300 isso é inofensivo — a posição não move preço. Com capital real a
premissa quebra: quando a ordem vira fração material do volume diário, o
preço de execução piora, e o efeito é **não-linear**.

Consequência: todo backtest do repositório superestimava o retorno de uma
carteira grande, e superestimava mais quanto maior o capital. Sem este termo
não é possível responder "qual o capital MÁXIMO antes do edge desaparecer".

MODELO ESCOLHIDO — lei da raiz quadrada (Almgren et al., Grinold & Kahn):

    slippage_por_ponta = coef * sigma_diaria * sqrt(valor_ordem / ADTV)

`sigma_diaria` é a volatilidade do ativo e `ADTV` o volume financeiro médio
diário. É o modelo padrão de impacto temporário na literatura, e a escolha da
raiz (em vez de linear) importa: linear puniria demais ordens grandes e de
menos as pequenas. `coef` fica explícito e é tratado como conservador.

Um trade = duas pontas (entrada e saída), então o round-trip paga 2x.
"""
from datetime import date

import numpy as np
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


def _liquidez(dados, adtv_brl: float, sigma: float = 0.02):
    """ADTV e volatilidade constantes por simplicidade do teste."""
    ts = dados["TESTE3.SA"]["ts"]
    return ({"TESTE3.SA": {d: adtv_brl for d in ts}},
            {"TESTE3.SA": {d: sigma for d in ts}})


def _roda(dados, janela, capital=300.0, **kw):
    inicio, fim = janela
    return run_regime_backtest(
        data=dados, regime_name="impacto", start=inicio, end=fim,
        capital=capital, ibov_filter=False, warmup_bars=300, **kw,
    )


class TestImpactoDeMercado:
    def test_desligado_por_padrao(self, dados, janela):
        """Guarda de regressão: sem ADTV configurado, nada muda."""
        adtv, vol = _liquidez(dados, 1e9)
        base = _roda(dados, janela)
        com = _roda(dados, janela, adtv_brl=adtv, daily_vol=vol, slippage_coef=0.0)
        assert [t.pnl_pct for t in base.trades] == [t.pnl_pct for t in com.trades]

    def test_desconta_duas_pontas_pela_raiz_da_participacao(self, dados, janela):
        """A fórmula tem de bater exatamente: 2 * coef * sigma * sqrt(valor/ADTV).
        É esta não-linearidade que faz o custo explodir com o capital."""
        adtv_v, sigma, coef = 5_000_000.0, 0.02, 1.0
        adtv, vol = _liquidez(dados, adtv_v, sigma)
        base = _roda(dados, janela)
        com = _roda(dados, janela, adtv_brl=adtv, daily_vol=vol, slippage_coef=coef)
        assert base.trades and com.trades

        t0, t1 = base.trades[0], com.trades[0]
        assert t0.capital_allocated == pytest.approx(t1.capital_allocated)
        esperado = 2 * coef * sigma * np.sqrt(t0.capital_allocated / adtv_v)
        assert (t0.pnl_pct - t1.pnl_pct) == pytest.approx(esperado, abs=1e-6)

    def test_ativo_mais_liquido_custa_menos(self, dados, janela):
        """O ponto econômico: a MESMA ordem custa menos num papel líquido.
        Se o modelo não separar isso, não mede capacidade."""
        adtv_alto, vol = _liquidez(dados, 500_000_000.0)
        adtv_baixo, _ = _liquidez(dados, 500_000.0)
        liq = _roda(dados, janela, adtv_brl=adtv_alto, daily_vol=vol, slippage_coef=1.0)
        ilq = _roda(dados, janela, adtv_brl=adtv_baixo, daily_vol=vol, slippage_coef=1.0)
        assert liq.trades and ilq.trades
        assert liq.trades[0].pnl_pct > ilq.trades[0].pnl_pct

    def test_custo_cresce_com_a_raiz_do_capital_nao_linearmente(self, dados, janela):
        """Capital 100x maior => posição 100x maior => slippage 10x (raiz), não
        100x. Se este teste falhar, o modelo virou linear e a curva de
        capacidade fica errada por ordens de grandeza."""
        adtv, vol = _liquidez(dados, 1_000_000_000.0)
        kw = dict(adtv_brl=adtv, daily_vol=vol, slippage_coef=1.0)
        p = _roda(dados, janela, capital=1_000.0, **kw)
        g = _roda(dados, janela, capital=100_000.0, **kw)
        assert p.trades and g.trades

        base_p = _roda(dados, janela, capital=1_000.0)
        base_g = _roda(dados, janela, capital=100_000.0)
        slip_p = base_p.trades[0].pnl_pct - p.trades[0].pnl_pct
        slip_g = base_g.trades[0].pnl_pct - g.trades[0].pnl_pct
        # posição 100x maior -> slippage ~10x (sqrt), com folga de tolerância
        assert 8.0 < (slip_g / slip_p) < 12.0

    def test_sem_dado_de_liquidez_para_o_ticker_nao_quebra(self, dados, janela):
        """Fail-safe: ticker ausente do mapa de ADTV não pode derrubar o
        backtest nem inventar custo — simplesmente não aplica slippage."""
        r = _roda(dados, janela, adtv_brl={"OUTRO3.SA": {}},
                  daily_vol={"OUTRO3.SA": {}}, slippage_coef=1.0)
        base = _roda(dados, janela)
        assert [t.pnl_pct for t in base.trades] == [t.pnl_pct for t in r.trades]


class TestSensibilidadeAoModeloDeImpacto:
    """A ressalva permanente: o modelo de impacto é ESTIMATIVA. A forma da curva
    (piora com capital) é robusta; o ponto exato onde o edge some não é. Estes
    testes travam o que muda quando se troca a premissa."""

    def test_expoente_linear_pune_mais_que_raiz(self, dados, janela):
        """Linear (expoente 1.0) vs raiz (0.5): para participação < 100%, a raiz
        dá custo MAIOR que o linear (sqrt(x) > x quando x<1). Inverter isso
        significaria que a escolha do modelo não está fazendo o que se pensa."""
        adtv, vol = _liquidez(dados, 10_000_000.0)
        kw = dict(adtv_brl=adtv, daily_vol=vol, slippage_coef=1.0)
        raiz = _roda(dados, janela, slippage_exponent=0.5, **kw)
        linear = _roda(dados, janela, slippage_exponent=1.0, **kw)
        assert raiz.trades and linear.trades
        # participação << 1, logo sqrt(p) > p  =>  custo raiz > custo linear
        assert raiz.trades[0].pnl_pct < linear.trades[0].pnl_pct

    def test_coeficiente_escala_o_custo_linearmente(self, dados, janela):
        """coef=0.5 tem de custar exatamente METADE de coef=1.0 — é o parâmetro
        que carrega toda a incerteza do modelo, então precisa ser previsível."""
        # ADTV pequeno de propósito: o slippage precisa ser grande o bastante
        # para não ser engolido pelo round(pnl_pct, 6) com que o Trade é gravado.
        adtv, vol = _liquidez(dados, 10_000.0)
        kw = dict(adtv_brl=adtv, daily_vol=vol)
        base = _roda(dados, janela)
        meio = _roda(dados, janela, slippage_coef=0.5, **kw)
        cheio = _roda(dados, janela, slippage_coef=1.0, **kw)
        s_meio = base.trades[0].pnl_pct - meio.trades[0].pnl_pct
        s_cheio = base.trades[0].pnl_pct - cheio.trades[0].pnl_pct
        assert s_cheio == pytest.approx(2 * s_meio, abs=1e-6)
