"""
`run_regime_backtest` aceita a função de sinal como parâmetro.

Até aqui o engine chamava `compute_signal` (Donchian) fixo. Para comparar
FAMÍLIAS de estratégia sob a mesma régua — mesmo custo, mesmo benchmark, mesma
janela, mesmo filtro de liquidez —, a família precisa ser o parâmetro e todo o
resto precisa ficar constante. Reimplementar o loop por família daria a
comparação errada: qualquer diferença de contabilidade viraria "alfa".
"""
import pandas as pd
import pytest

from trading_bot.backtest.engine import run_regime_backtest
from trading_bot.signals.engine import Candidate
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
        data=dados, regime_name="sig", start=inicio, end=fim,
        capital=1000.0, ibov_filter=False, warmup_bars=300, **kw,
    )


class TestSinalPlugavel:
    def test_default_continua_sendo_o_donchian(self, dados, janela):
        """Guarda de regressão: sem passar nada, o comportamento é o de sempre."""
        from trading_bot.signals.engine import compute_signal

        base = _roda(dados, janela)
        expl = _roda(dados, janela, signal_fn=compute_signal)
        assert [t.entry_date for t in base.trades] == [t.entry_date for t in expl.trades]

    def test_sinal_que_nunca_dispara_produz_zero_trades(self, dados, janela):
        r = _roda(dados, janela, signal_fn=lambda df, ticker, **kw: None)
        assert r.trades == []

    def test_sinal_customizado_gera_trade_com_stop_e_alvo_proprios(self, dados, janela):
        """A família decide entrada, stop e alvo; o engine só executa e
        contabiliza. É o que garante que a comparação isola a ESTRATÉGIA."""
        def sempre(df, ticker, **kw):
            p = float(df["adj_close"].iloc[-1])
            return Candidate(
                ticker=ticker, score=1.0, entry_price=p,
                stop=p * 0.90, target=p * 1.20,
                signal_ts=df["ts"].iloc[-1], rsi=50.0, volume_ratio=1.0,
                near_support=False, signal_details={},
            )
        r = _roda(dados, janela, signal_fn=sempre)
        assert r.trades
        t = r.trades[0]
        assert t.stop < t.entry_price < t.target

    def test_score_ordena_os_candidatos(self, dados, janela):
        """Cross-sectional (ex.: momentum por ranking) depende disto: o engine
        ordena por score e pega os melhores dentro dos slots livres."""
        dados["OUTRO3.SA"] = _serie_com_breakout_na_janela()

        def por_ticker(df, ticker, **kw):
            p = float(df["adj_close"].iloc[-1])
            return Candidate(
                ticker=ticker, score=(9.0 if ticker == "OUTRO3.SA" else 1.0),
                entry_price=p, stop=p * 0.9, target=p * 1.2,
                signal_ts=df["ts"].iloc[-1], rsi=50.0, volume_ratio=1.0,
                near_support=False, signal_details={},
            )
        r = _roda(dados, janela, max_positions=1, signal_fn=por_ticker)
        assert r.trades
        assert r.trades[0].ticker == "OUTRO3.SA"
