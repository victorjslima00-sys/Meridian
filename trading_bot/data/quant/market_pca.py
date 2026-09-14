r"""
Motor de PCA (Principal Components Analysis) para Fatores Sistemicos de Mercado
Head of Data Engineering: Orion
Meridian Technologies

Fundamentacao Matematica:
Stanford CS229 (Capitulo 12 — Principal Components Analysis, Andrew Ng & Tengyu Ma)
Passos do Algoritmo CS229:
  1. Padronizacao das features com media zero e variancia unitaria (CS229 p. 168):
     x_j^{(i)} \leftarrow \frac{x_j^{(i)} - \mu_j}{\sigma_j}
  2. Calculo da Matriz de Covariancia Empirica (CS229 p. 171):
     \Sigma = \frac{1}{n} \sum_{i=1}^n x^{(i)} (x^{(i)})^T
  3. Decomposicao em Autovetores e Autovalores (CS229 p. 171):
     \Sigma u = \lambda u
  4. Projecao no Subespaco dos k Autovetores Principais (CS229 p. 171, Eq. 171):
     y^{(i)} = [u_1^T x^{(i)}, \dots, u_k^T x^{(i)}]^T
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class MarketPCAEngine:
    """
    Motor de analise de componentes principais para reducao de dimensionalidade,
    deteccao de fatores macro de risco e filtragem de correlacoes espurias em carteiras.
    """

    def __init__(self, n_components: int = 2):
        self.n_components = n_components
        self.components_: Optional[np.ndarray] = None
        self.explained_variance_ratio_: Optional[np.ndarray] = None
        self.mean_: Optional[np.ndarray] = None
        self.std_: Optional[np.ndarray] = None

    def fit(self, X: np.ndarray) -> MarketPCAEngine:
        """
        Ajusta o PCA sobre a matriz de dados X (dimensao: n_amostras x n_features).
        """
        n_samples, n_features = X.shape
        k = min(self.n_components, n_features)

        # 1. Normalizacao: media zero e variancia unitaria (CS229 p. 168)
        self.mean_ = np.mean(X, axis=0)
        self.std_ = np.std(X, axis=0)
        # Evita divisao por zero
        safe_std = np.where(self.std_ == 0, 1.0, self.std_)
        X_norm = (X - self.mean_) / safe_std

        # 2. Matriz de Covariancia Empirica (CS229 p. 171)
        cov_matrix = np.dot(X_norm.T, X_norm) / n_samples

        # 3. Calculo de Autovalores e Autovetores (Hermitiana/Simetrica)
        eigenvalues, eigenvectors = np.linalg.eigh(cov_matrix)

        # Ordenacao decrescente (do maior autovalor para o menor)
        idx = np.argsort(eigenvalues)[::-1]
        sorted_eigenvalues = eigenvalues[idx]
        sorted_eigenvectors = eigenvectors[:, idx]

        # Seleciona os k componentes principais
        self.components_ = sorted_eigenvectors[:, :k].T
        total_variance = np.sum(sorted_eigenvalues)
        if total_variance > 0:
            self.explained_variance_ratio_ = sorted_eigenvalues[:k] / total_variance
        else:
            self.explained_variance_ratio_ = np.zeros(k)

        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        """
        Projeta os dados nos componentes principais aprendidos (CS229 p. 171).
        """
        if self.components_ is None or self.mean_ is None or self.std_ is None:
            raise ValueError("O modelo PCA precisa ser ajustado com fit() antes de transform()")

        safe_std = np.where(self.std_ == 0, 1.0, self.std_)
        X_norm = (X - self.mean_) / safe_std
        return np.dot(X_norm, self.components_.T)

    def fit_transform(self, X: np.ndarray) -> np.ndarray:
        return self.fit(X).transform(X)
