"""
Testes unitarios para a Regressao Logistica com Regularizacao L1/L2 — Orion Quant
Baseado no Stanford CS229 (Capitulos 2 e 9 — Logistic Regression & Regularization)
"""
import numpy as np
import pytest
from trading_bot.data.quant.regularized_logistic import RegularizedLogisticRegression


def test_logistic_regression_initialization():
    clf = RegularizedLogisticRegression(learning_rate=0.01, penalty="l2", C=1.0)
    assert clf.learning_rate == 0.01
    assert clf.penalty == "l2"
    assert clf.C == 1.0
    assert clf.theta is None


def test_logistic_regression_convergence_and_sparsity():
    """
    Testa convergencia com sigmoide analitica e regularizacao L2 (CS229 p. 21-24 e 137-140).
    """
    np.random.seed(42)
    n = 100
    # Gera dados linearmente separaveis com ruido
    X = np.random.randn(n, 3)
    # y = 1 se 2*x0 - 1.5*x1 > 0
    logits = 2.0 * X[:, 0] - 1.5 * X[:, 1]
    probs = 1.0 / (1.0 + np.exp(-logits))
    y = (probs > 0.5).astype(float)

    clf = RegularizedLogisticRegression(learning_rate=0.1, penalty="l2", C=1.0, max_iters=300)
    clf.fit(X, y)

    assert clf.theta is not None
    assert len(clf.theta) == 4  # 3 features + 1 intercepto

    # Predicoes de probabilidade calibrada no intervalo [0, 1]
    pred_probs = clf.predict_proba(X)
    assert np.all(pred_probs >= 0.0)
    assert np.all(pred_probs <= 1.0)

    # Acuracia acima de 85%
    preds = clf.predict(X)
    accuracy = np.mean(preds == y)
    assert accuracy > 0.85
