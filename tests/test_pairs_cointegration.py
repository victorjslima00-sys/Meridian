"""
Testes unitarios para o Motor de Otimizacao e Geracao de Sinais de Pares — Orion Quant
Baseado no Stanford CS229 (Capitulo 1 — Linear Regression & Normal Equations)
"""
import numpy as np
import pandas as pd
import pytest
from trading_bot.data.quant.pairs_cointegration import PairsCointegrationEngine


def test_pairs_engine_initialization():
    engine = PairsCointegrationEngine(window=60, zscore_threshold=2.0)
    assert engine.window == 60
    assert engine.zscore_threshold == 2.0


def test_pairs_hedge_ratio_and_spread():
    """
    Testa calculo da razao de hedge beta via Equacoes Normais (CS229 p. 14-17).
    """
    np.random.seed(42)
    n = 100
    # Serie base (ex: PETR4)
    x = np.linspace(30.0, 40.0, n) + np.random.normal(0, 0.2, n)
    # Serie cointegrada (ex: PETR3): y = 1.2 * x + 2.0 + ruido branco estacionario
    true_beta = 1.2
    true_alpha = 2.0
    noise = np.random.normal(0, 0.1, n)
    y = true_beta * x + true_alpha + noise

    engine = PairsCointegrationEngine(window=50)
    res = engine.calculate_pair_spread(x, y)

    assert "hedge_ratio" in res
    assert "spread" in res
    assert "zscore" in res
    # Beta estimado via OLS deve ser proximo de 1.2
    assert res["hedge_ratio"] == pytest.approx(true_beta, abs=0.05)
    assert len(res["spread"]) == n
    assert len(res["zscore"]) == n


def test_pairs_trading_signals():
    engine = PairsCointegrationEngine(zscore_threshold=2.0)
    # Z-scores simulando desvios extremos (-2.5, 0.0, +2.5)
    zscores = np.array([-2.5, -1.0, 0.0, 1.5, 2.5, 0.5])
    signals = engine.generate_signals(zscores)

    # -2.5 deve gerar compra do par (+1), +2.5 deve gerar venda (-1), 0 deve desarmar (0)
    assert signals[0] == 1.0
    assert signals[2] == 0.0
    assert signals[4] == -1.0
