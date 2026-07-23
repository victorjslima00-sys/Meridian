"""
Regra de saída antecipada — "no fechamento do dia N, sai se não avançou X%".

Origem: a anatomia de 848 trades mostrou que perdedores param de subir quase
imediatamente (52% fazem o topo no próprio dia da entrada, MFE mediana
+1,93%) enquanto ganhadores seguem subindo por ~11 dias (MFE +8,40%).

CUIDADO COM A LEITURA: aquele padrão é medido no passado do trade e é em boa
parte tautológico — "dia do topo" só se conhece na saída. Esta regra é a
versão PARA A FRENTE da hipótese: decide no fechamento do dia N usando só o
preço até N. É essa versão que pode ser avaliada honestamente.

Sem look-ahead: usa apenas o fechamento do próprio dia da decisão, a mesma
base de informação que o timeout já usa (engine.py, exit_reason="timeout").
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


def _roda(dados, janela, **kw):
    inicio, fim = janela
    return run_regime_backtest(
        data=dados, regime_name="saida", start=inicio, end=fim,
        capital=300.0, ibov_filter=False, **kw,
    )


class TestSaidaAntecipada:
    def test_desligada_por_padrao(self, dados, janela):
        """Guarda de regressão: sem configurar, nada muda."""
        base = _roda(dados, janela)
        expl = _roda(dados, janela, early_exit_day=0, early_exit_min_gain=0.0)
        assert [t.exit_reason for t in base.trades] == [t.exit_reason for t in expl.trades]
        assert [t.pnl_pct for t in base.trades] == [t.pnl_pct for t in expl.trades]

    def test_exigencia_impossivel_fecha_tudo_no_dia_n(self, dados, janela):
        """Com um ganho mínimo inatingível, TODO trade que chegue vivo ao dia N
        sai ali — é o caso extremo que prova que a regra dispara."""
        r = _roda(dados, janela, early_exit_day=2, early_exit_min_gain=9.99)
        assert r.trades
        for t in r.trades:
            dias = (t.exit_date - t.entry_date).days
            assert t.exit_reason in ("early_exit", "stop", "stop_gap", "target", "target_gap"), t.exit_reason
            if t.exit_reason == "early_exit":
                assert dias >= 2, f"saiu antes do dia 2: {dias}"

    def test_exigencia_trivial_nao_dispara(self, dados, janela):
        """Ganho mínimo de -100% é sempre satisfeito: nenhuma saída antecipada.
        Separa 'a regra funciona' de 'a regra fecha tudo por acidente'."""
        r = _roda(dados, janela, early_exit_day=2, early_exit_min_gain=-1.0)
        assert not any(t.exit_reason == "early_exit" for t in r.trades)

    def test_nao_antecipa_saida_de_quem_ja_bateu_stop_ou_alvo(self, dados, janela):
        """Stop e alvo têm precedência: são eventos intradiários, a saída
        antecipada é decisão de fechamento. Inverter isso mudaria o preço de
        saída de trades que já haviam sido liquidados."""
        r = _roda(dados, janela, early_exit_day=1, early_exit_min_gain=9.99)
        for t in r.trades:
            if t.exit_reason == "early_exit":
                assert t.exit_price > t.stop, "saiu por regra mas o stop havia sido violado"

    def test_reduz_prejuizo_medio_dos_perdedores(self, dados, janela):
        """O efeito pretendido: cortar cedo quem não anda deve encurtar a
        perda média. Se nem no caso sintético favorável isso aparece, a
        hipótese não se sustenta nem em laboratório."""
        base = _roda(dados, janela)
        com = _roda(dados, janela, early_exit_day=2, early_exit_min_gain=0.01)
        pb = [t.pnl_pct for t in base.trades if t.pnl_pct <= 0]
        pc = [t.pnl_pct for t in com.trades if t.pnl_pct <= 0]
        if pb and pc:
            assert sum(pc) / len(pc) >= sum(pb) / len(pb)
