r"""
Motor de Redes Neurais e Deep Learning Construido 100% do Zero (Pure NumPy)
Head of Data Engineering: Orion
Meridian Technologies

Fundamentacao Matematica:
Stanford CS229 (Capitulo 7 — Deep Learning & Backpropagation, Ma & Ng 2026)
Equacoes Implementadas:
  - Propagacao Direta (Eq. 7.76): z^[k] = W^[k] a^[k-1] + b^[k], a^[k] = \sigma(z^[k])
  - Regra de Atualizacao da Cadeia / Backward Pass (Eq. 7.80 - 7.84):
      \frac{\partial J}{\partial z^{[r]}} = a^{[r]} - y  (Logistic Loss / Cross-Entropy)
      \frac{\partial J}{\partial W^{[k]}} = \frac{1}{m} (a^{[k-1]})^T \frac{\partial J}{\partial z^{[k]}}
      \frac{\partial J}{\partial b^{[k]}} = \frac{1}{m} \sum \frac{\partial J}{\partial z^{[k]}}
      \frac{\partial J}{\partial z^{[k-1]}} = \left(\frac{\partial J}{\partial z^{[k]}} (W^{[k]})^T\right) \odot \sigma'(z^{[k-1]})
  - Regularizacao L2 / Weight Decay (Capitulo 9.1, Eq. 9.2):
      W \leftarrow (1 - \alpha \lambda) W - \alpha \nabla_W J
"""
from __future__ import annotations

import logging
from typing import List, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class MLPFromScratch:
    """
    Multi-Layer Perceptron (Rede Neural Profunda Totalmente Conectada)
    implementada do zero absoluto, sem PyTorch/TensorFlow/Scikit-Learn.
    """

    def __init__(
        self,
        layer_dims: List[int],
        learning_rate: float = 0.05,
        l2_lambda: float = 1e-4,
    ):
        """
        layer_dims: ex [input_dim, hidden_1, ..., output_dim]
        """
        self.layer_dims = layer_dims
        self.learning_rate = learning_rate
        self.l2_lambda = l2_lambda
        self.name = "MLPFromScratch"
        self.version = "v1.0.0-research"
        self.weights: List[np.ndarray] = []
        self.biases: List[np.ndarray] = []
        self._initialize_parameters()

    def _initialize_parameters(self) -> None:
        """
        Inicializacao He / Xavier baseada no CS229 para evitar explosao/desaparecimento de gradientes.
        """
        for i in range(len(self.layer_dims) - 1):
            fan_in = self.layer_dims[i]
            fan_out = self.layer_dims[i + 1]
            # He initialization para ReLU
            std = np.sqrt(2.0 / fan_in)
            W = np.random.randn(fan_in, fan_out) * std
            b = np.zeros((1, fan_out))
            self.weights.append(W)
            self.biases.append(b)

    @staticmethod
    def _relu(z: np.ndarray) -> np.ndarray:
        return np.maximum(0.0, z)

    @staticmethod
    def _relu_deriv(z: np.ndarray) -> np.ndarray:
        return (z > 0.0).astype(float)

    @staticmethod
    def _sigmoid(z: np.ndarray) -> np.ndarray:
        # Sigmoid estavel numericamente
        return np.where(z >= 0, 1.0 / (1.0 + np.exp(-z)), np.exp(z) / (1.0 + np.exp(z)))

    def forward(self, X: np.ndarray) -> Tuple[np.ndarray, List[Tuple[np.ndarray, np.ndarray]]]:
        """
        Propagacao direta (Forward pass, Eq. 7.76).
        Retorna as predicoes e o cache de ativacoes para o backpropagation.
        """
        cache = []
        a_current = X

        num_layers = len(self.weights)
        for k in range(num_layers):
            W = self.weights[k]
            b = self.biases[k]
            z = np.dot(a_current, W) + b

            if k == num_layers - 1:
                # Ultima camada: Sigmoid para probabilidade [0, 1]
                a_next = self._sigmoid(z)
            else:
                # Camadas ocultas: ReLU
                a_next = self._relu(z)

            cache.append((a_current, z))
            a_current = a_next

        return a_current, cache

    def compute_loss(self, y_pred: np.ndarray, y_true: np.ndarray) -> float:
        """
        Binary Cross-Entropy Loss com regularizacao L2 (Eq. 7.4 e Eq. 9.1).
        """
        if y_true.ndim == 1:
            y_true = y_true.reshape(-1, 1)
        m = y_true.shape[0]
        epsilon = 1e-15
        y_clipped = np.clip(y_pred, epsilon, 1.0 - epsilon)
        bce_loss = -np.mean(y_true * np.log(y_clipped) + (1.0 - y_true) * np.log(1.0 - y_clipped))

        # Regularizacao L2 (CS229 Cap. 9.1)
        l2_penalty = (self.l2_lambda / (2.0 * m)) * sum(np.sum(W ** 2) for W in self.weights)
        return float(bce_loss + l2_penalty)

    def backward(
        self,
        y_pred: np.ndarray,
        y_true: np.ndarray,
        cache: List[Tuple[np.ndarray, np.ndarray]],
    ) -> Tuple[List[np.ndarray], List[np.ndarray]]:
        """
        Propagacao retrograda (Backpropagation analitico, Eq. 7.80 - 7.84).
        """
        if y_true.ndim == 1:
            y_true = y_true.reshape(-1, 1)
        m = y_true.shape[0]
        num_layers = len(self.weights)
        grad_W = [np.zeros_like(W) for W in self.weights]
        grad_b = [np.zeros_like(b) for b in self.biases]

        # Gradiente na camada de saida (Eq. 7.80: dJ/dz^[r] = a^[r] - y)
        dz = y_pred - y_true

        for k in reversed(range(num_layers)):
            a_prev, z = cache[k]

            # Gradiente w.r.t pesos e bias (Eq. 7.81 e 7.82)
            grad_W[k] = (np.dot(a_prev.T, dz) / m) + (self.l2_lambda / m) * self.weights[k]
            grad_b[k] = np.sum(dz, axis=0, keepdims=True) / m

            if k > 0:
                # Propaga gradiente para a camada anterior (Eq. 7.83 e 7.84)
                da_prev = np.dot(dz, self.weights[k].T)
                _, z_prev = cache[k - 1]
                dz = da_prev * self._relu_deriv(z_prev)

        return grad_W, grad_b

    def fit(self, X: np.ndarray, y: np.ndarray, epochs: int = 500) -> List[float]:
        """
        Treinamento com Gradient Descent analitico e decaimento de pesos (Eq. 9.2).
        """
        if y.ndim == 1:
            y = y.reshape(-1, 1)
        losses = []
        for epoch in range(epochs):
            y_pred, cache = self.forward(X)
            loss = self.compute_loss(y_pred, y)
            losses.append(loss)

            grad_W, grad_b = self.backward(y_pred, y, cache)

            # Atualizacao dos parametros via SGD / Gradient Descent
            for k in range(len(self.weights)):
                self.weights[k] -= self.learning_rate * grad_W[k]
                self.biases[k] -= self.learning_rate * grad_b[k]

        return losses

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        Retorna as probabilidades preditas da camada de saida sigmoide.
        """
        y_pred, _ = self.forward(X)
        return y_pred

    def predict(self, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        """
        Gera predicoes discretas [0.0, 1.0] a partir do forward pass com base no limiar especificado.
        Retorna array NumPy compativel com o avaliador ModelEvaluationAgent.
        """
        probs = self.predict_proba(X)
        preds = (probs >= threshold).astype(float)
        if preds.ndim > 1 and preds.shape[1] == 1:
            return preds.flatten()
        return preds
