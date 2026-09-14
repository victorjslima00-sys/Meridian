r"""
Motor de Regressao Logistica com Regularizacao L1 (Lasso) e L2 (Ridge) do Zero
Head of Data Engineering: Orion
Meridian Technologies

Fundamentacao Matematica:
Stanford CS229 (Capitulo 2 — Classification and Logistic Regression & Capitulo 9 — Regularization, Andrew Ng & Tengyu Ma)
Equacoes Implementadas:
  1. Funcao Hipotese Sigmoide (CS229 Eq. 2.1, p. 21):
     h_\theta(x) = g(\theta^T x) = \frac{1}{1 + e^{-\theta^T x}}
  2. Custo Regularizado com Entropia Cruzada Negativa (CS229 p. 23 e 137):
     J(\theta) = -\frac{1}{m} \sum_{i=1}^m [y^{(i)} \log(h_\theta(x^{(i)})) + (1 - y^{(i)}) \log(1 - h_\theta(x^{(i)}))] + \frac{\lambda}{2m} \|\theta_{1:d}\|_2^2
  3. Gradiente Analitico com Decaimento de Pesos (CS229 Eq. 2.2 e Eq. 9.2):
     \frac{\partial J}{\partial \theta_j} = \frac{1}{m} \sum_{i=1}^m (h_\theta(x^{(i)}) - y^{(i)}) x_j^{(i)} + \frac{\lambda}{m} \theta_j \quad (j \ge 1)
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class RegularizedLogisticRegression:
    """
    Classificador de probabilidade de vitoria (Win Probability Estimator)
    construido puramente em algebra matricial NumPy com regularizacao contra overfitting.
    """

    def __init__(
        self,
        learning_rate: float = 0.05,
        penalty: str = "l2",
        C: float = 1.0,           # Inverso da forca de regularizacao (lambda = 1.0 / C)
        max_iters: int = 500,
        tol: float = 1e-5,
    ):
        self.learning_rate = learning_rate
        self.penalty = penalty.lower()
        self.C = max(C, 1e-5)
        self.lmbda = 1.0 / self.C
        self.max_iters = max_iters
        self.tol = tol
        self.theta: Optional[np.ndarray] = None
        self.loss_history: list[float] = []

    @staticmethod
    def _sigmoid(z: np.ndarray) -> np.ndarray:
        return np.where(z >= 0, 1.0 / (1.0 + np.exp(-z)), np.exp(z) / (1.0 + np.exp(z)))

    def _add_intercept(self, X: np.ndarray) -> np.ndarray:
        intercept = np.ones((X.shape[0], 1))
        return np.hstack((intercept, X))

    def fit(self, X: np.ndarray, y: np.ndarray) -> RegularizedLogisticRegression:
        m, d = X.shape
        X_b = self._add_intercept(X)
        self.theta = np.zeros(d + 1)
        y = y.reshape(-1)

        self.loss_history = []

        for _ in range(self.max_iters):
            logits = np.dot(X_b, self.theta)
            preds = self._sigmoid(logits)

            # Gradiente analitico (CS229 Eq. 2.2)
            error = preds - y
            grad = np.dot(X_b.T, error) / m

            # Penalidade de regularizacao (nao regulariza o intercepto theta_0)
            if self.penalty == "l2":
                reg_term = (self.lmbda / m) * np.r_[0.0, self.theta[1:]]
                grad += reg_term
            elif self.penalty == "l1":
                reg_term = (self.lmbda / m) * np.r_[0.0, np.sign(self.theta[1:])]
                grad += reg_term

            theta_prev = self.theta.copy()
            self.theta -= self.learning_rate * grad

            # Calculo do custo
            eps = 1e-15
            p_clip = np.clip(preds, eps, 1.0 - eps)
            loss = -np.mean(y * np.log(p_clip) + (1.0 - y) * np.log(1.0 - p_clip))
            self.loss_history.append(float(loss))

            if np.linalg.norm(self.theta - theta_prev) < self.tol:
                break

        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.theta is None:
            raise ValueError("O modelo precisa ser ajustado com fit() primeiro.")
        X_b = self._add_intercept(X)
        return self._sigmoid(np.dot(X_b, self.theta))

    def predict(self, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        return (self.predict_proba(X) >= threshold).astype(float)
