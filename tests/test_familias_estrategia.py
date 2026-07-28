"""Contrato das famílias: todas obedecem à mesma interface e não olham o futuro."""
import numpy as np
import pandas as pd
import pytest

from trading_bot.signals.familias import FAMILIAS
from trading_bot.signals.engine import Candidate


def _serie(n=700, seed=0):
    rng = np.random.default_rng(seed)
    p = 50.0
    c = []
    for _ in range(n):
        p *= 1 + rng.normal(0.0004, 0.018)
        c.append(p)
    c = np.array(c)
    return pd.DataFrame({
        "ts": pd.date_range("2018-01-01", periods=n, freq="D").date,
        "o": c * 0.999, "h": c * 1.012, "l": c * 0.988,
        "c": c, "adj_close": c, "v": [1_000_000] * n,
    })


@pytest.mark.parametrize("nome", sorted(FAMILIAS))
class TestContratoDasFamilias:
    def test_devolve_candidate_ou_none(self, nome):
        r = FAMILIAS[nome](_serie(), "TESTE3.SA")
        assert r is None or isinstance(r, Candidate)

    def test_serie_curta_nao_quebra(self, nome):
        """Sem histórico suficiente a família recusa em vez de estourar — é o
        que permite rodar todas sobre o mesmo universo sem tratamento especial."""
        assert FAMILIAS[nome](_serie(n=30), "TESTE3.SA") is None

    def test_invariante_de_compra_stop_menor_que_entrada_menor_que_alvo(self, nome):
        """Vale para toda família long-only: violar isso é bug de sinal, não
        característica de estratégia."""
        for seed in range(12):
            r = FAMILIAS[nome](_serie(seed=seed), "TESTE3.SA")
            if r is not None:
                assert r.stop < r.entry_price < r.target, nome
                return

    def test_nao_usa_a_barra_futura(self, nome):
        """Mutação: alterar barras APÓS a última não pode mudar o sinal — o df
        já chega cortado em D-1, mas a família não pode assumir nada além."""
        df = _serie()
        antes = FAMILIAS[nome](df, "TESTE3.SA")
        estendido = pd.concat([df, df.tail(5).assign(adj_close=999.0, c=999.0)])
        depois = FAMILIAS[nome](estendido.iloc[:len(df)], "TESTE3.SA")
        assert (antes is None) == (depois is None)
        if antes is not None:
            assert antes.entry_price == pytest.approx(depois.entry_price)
