"""
Custo de corretagem com componente FIXO por ordem.

O modelo anterior era 100% percentual:
`round_trip = (brokerage_pct + spread_pct) * 2`, subtraído do `pnl_pct`.
Isso assume implicitamente que o custo escala com o tamanho da posição — o
que é verdade para spread e emolumentos, e FALSO para corretagem fixa.

A distinção decide a viabilidade do bot: R$2,50 por ordem numa posição de
R$75 é 3,3% por ponta, 6,7% no round-trip. Nenhum edge de +0,5%/trade
sobrevive a isso. Na mesma posição com R$50.000 de capital, a mesma taxa é
0,04%. O custo fixo não é um detalhe de configuração — é o que define o
capital mínimo operável.
"""
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


def _roda(dados, janela, capital=300.0, **kw):
    inicio, fim = janela
    return run_regime_backtest(
        data=dados, regime_name="custo", start=inicio, end=fim,
        capital=capital, ibov_filter=False, **kw,
    )


class TestCustoFixoPorOrdem:
    def test_taxa_zero_preserva_o_comportamento_atual(self, dados, janela):
        """Guarda de regressão: quem não configurar taxa fixa não vê mudança."""
        base = _roda(dados, janela)
        com_zero = _roda(dados, janela, fixed_fee_per_order=0.0)
        assert [t.pnl_pct for t in base.trades] == [t.pnl_pct for t in com_zero.trades]

    def test_desconta_duas_ordens_por_trade(self, dados, janela):
        """Um trade = duas ordens (entrada + saída). O desconto no pnl_pct tem
        de ser exatamente 2*taxa/capital_alocado — só assim a taxa fixa pesa
        mais em posição pequena, que é o efeito que importa medir."""
        taxa = 2.50
        base = _roda(dados, janela)
        com_taxa = _roda(dados, janela, fixed_fee_per_order=taxa)
        assert base.trades and com_taxa.trades

        t0, t1 = base.trades[0], com_taxa.trades[0]
        # O primeiro trade ocorre com o capital ainda intacto nas duas rodadas,
        # então é comparável ponta a ponta.
        assert t0.capital_allocated == pytest.approx(t1.capital_allocated)
        esperado = (taxa * 2) / t0.capital_allocated
        # `Trade.pnl_pct` é gravado com round(..., 6) — a tolerância acompanha
        # a precisão armazenada, não a do float.
        assert (t0.pnl_pct - t1.pnl_pct) == pytest.approx(esperado, abs=1e-6)

    def test_pesa_mais_em_capital_menor(self, dados, janela):
        """O ponto econômico: a MESMA taxa é fatal em R$300 e irrelevante em
        R$50.000. Se este teste não separar os dois casos, o modelo de custo
        não está capturando o que decide o capital mínimo."""
        taxa = 2.50
        pequeno = _roda(dados, janela, capital=300.0, fixed_fee_per_order=taxa)
        grande = _roda(dados, janela, capital=50_000.0, fixed_fee_per_order=taxa)
        assert pequeno.trades and grande.trades

        def fracao(r):
            t = r.trades[0]
            return (taxa * 2) / t.capital_allocated

        assert fracao(pequeno) > 20 * fracao(grande)

    def test_taxa_fixa_pode_zerar_um_trade_vencedor(self, dados, janela):
        """Com capital pequeno, uma taxa alta transforma ganho em prejuízo —
        é exatamente o cenário que precisa aparecer na tabela de capital
        mínimo, e não aparecia num modelo só percentual."""
        base = _roda(dados, janela, capital=300.0)
        caro = _roda(dados, janela, capital=300.0, fixed_fee_per_order=5.0)
        assert base.trades and caro.trades
        assert caro.trades[0].pnl_pct < base.trades[0].pnl_pct
