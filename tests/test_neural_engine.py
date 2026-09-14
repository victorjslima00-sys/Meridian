"""
Testes unitarios para o Motor de Deep Learning do Zero — Orion Quant
Baseado no Stanford CS229 (Capitulo 7 — Deep Learning & Backpropagation)
"""
import numpy as np
import pytest
from trading_bot.data.quant.neural_engine import MLPFromScratch


def test_mlp_initialization():
    mlp = MLPFromScratch(layer_dims=[4, 8, 1], learning_rate=0.01)
    assert len(mlp.weights) == 2
    assert len(mlp.biases) == 2
    assert mlp.weights[0].shape == (4, 8)
    assert mlp.biases[0].shape == (1, 8)
    assert mlp.weights[1].shape == (8, 1)
    assert mlp.biases[1].shape == (1, 1)


def test_mlp_forward_pass():
    mlp = MLPFromScratch(layer_dims=[3, 4, 1])
    X = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    preds, cache = mlp.forward(X)
    assert preds.shape == (2, 1)
    assert len(cache) == 2


def test_mlp_training_convergence():
    """
    Testa aprendizado supervisionado de relacao nao-linear (XOR / classificacao binaria).
    Equacoes 7.76 - 7.84 do CS229 (Forward & Backward Pass).
    """
    np.random.seed(42)
    mlp = MLPFromScratch(layer_dims=[2, 8, 1], learning_rate=0.1)

    # Problema classico nao-linear XOR
    X = np.array([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]])
    y = np.array([[0.0], [1.0], [1.0], [0.0]])

    initial_loss = mlp.compute_loss(mlp.forward(X)[0], y)

    # Treina por 500 epocas usando Mini-Batch / Batch GD com Backprop analitica
    losses = mlp.fit(X, y, epochs=500)

    final_loss = losses[-1]
    assert final_loss < initial_loss
    assert final_loss < 0.1  # Convergencia com perda minima

    # Predicoes devem separar as classes
    preds, _ = mlp.forward(X)
    binary_preds = (preds > 0.5).astype(float)
    np.testing.assert_array_equal(binary_preds, y)
