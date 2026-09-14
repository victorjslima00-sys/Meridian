r"""
Motor de Agrupamento K-Means de Regimes de Volatilidade de Mercado 100% do Zero
Head of Data Engineering: Orion
Meridian Technologies

Fundamentacao Matematica:
Stanford CS229 (Capitulo 10 — Clustering and the k-means algorithm, Andrew Ng & Tengyu Ma)
Equacoes Implementadas (CS229 p. 147-148):
  1. Atribuicao do Cluster (Passo 1):
     c^{(i)} := \arg\min_j ||x^{(i)} - \mu_j||^2
  2. Atualizacao dos Centroides (Passo 2):
     \mu_j := \frac{\sum_{i=1}^n 1\{c^{(i)} = j\} x^{(i)}}{\sum_{i=1}^n 1\{c^{(i)} = j\}}
  3. Funcao de Distorcao J (Convergencia Monotonica via Descida Coordenada, p. 148):
     J(c, \mu) = \sum_{i=1}^n ||x^{(i)} - \mu_{c^{(i)}}||^2
"""
from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class MarketKMeansClustering:
    """
    Algoritmo K-Means implementado com algebra vetorial pura em NumPy para segmentar
    automaticamente o historico do ativo em regimes de volatilidade e liquidez.
    """

    def __init__(self, k: int = 3, max_iters: int = 100, tol: float = 1e-4, random_state: Optional[int] = None):
        self.k = k
        self.max_iters = max_iters
        self.tol = tol
        self.random_state = random_state
        self.centroids: Optional[np.ndarray] = None
        self.distortion_history: List[float] = []

    def fit(self, X: np.ndarray) -> MarketKMeansClustering:
        if self.random_state is not None:
            np.random.seed(self.random_state)

        n_samples, n_features = X.shape
        # Inicializacao aleatoria dos centroides a partir dos pontos da amostra (CS229 p. 147)
        random_indices = np.random.choice(n_samples, size=self.k, replace=False)
        self.centroids = X[random_indices].copy()

        self.distortion_history = []

        for _ in range(self.max_iters):
            # 1. Atribuicao de clusters (c^{(i)} := argmin ||x^{(i)} - \mu_j||^2)
            # Distancias euclidianas vetorizadas
            distances = np.linalg.norm(X[:, np.newaxis, :] - self.centroids[np.newaxis, :, :], axis=2) ** 2
            labels = np.argmin(distances, axis=1)

            # Calculo da funcao de distorcao J(c, \mu) (CS229 p. 148)
            distortion = float(np.sum(np.min(distances, axis=1)))
            self.distortion_history.append(distortion)

            # 2. Atualizacao dos centroides para a media dos pontos atribuidos
            new_centroids = np.zeros_like(self.centroids)
            for j in range(self.k):
                points_in_cluster = X[labels == j]
                if len(points_in_cluster) > 0:
                    new_centroids[j] = np.mean(points_in_cluster, axis=0)
                else:
                    new_centroids[j] = self.centroids[j]

            # Verificacao de convergencia
            centroid_shift = np.linalg.norm(new_centroids - self.centroids)
            self.centroids = new_centroids
            if centroid_shift < self.tol:
                break

        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.centroids is None:
            raise ValueError("Modelo nao ajustado. Execute fit() primeiro.")
        distances = np.linalg.norm(X[:, np.newaxis, :] - self.centroids[np.newaxis, :, :], axis=2) ** 2
        return np.argmin(distances, axis=1)

    def fit_predict(self, X: np.ndarray) -> np.ndarray:
        self.fit(X)
        return self.predict(X)
