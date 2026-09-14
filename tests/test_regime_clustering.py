"""
Testes unitarios para o Algoritmo K-Means de Regimes de Volatilidade do Zero — Orion Quant
Baseado no Stanford CS229 (Capitulo 10 — Clustering and the k-means algorithm)
"""
import numpy as np
import pytest
from trading_bot.data.quant.regime_clustering import MarketKMeansClustering


def test_kmeans_initialization():
    km = MarketKMeansClustering(k=3, max_iters=50)
    assert km.k == 3
    assert km.max_iters == 50
    assert km.centroids is None


def test_kmeans_convergence_and_clustering():
    """
    Testa convergencia por descida coordenada da funcao de distorcao (CS229 Cap 10, p. 148).
    """
    np.random.seed(42)
    # Simula 3 regimes de mercado nitidos (Baixa Vol, Media Vol, Alta Vol)
    cluster_low = np.random.normal(loc=[10.0, 0.5], scale=0.5, size=(30, 2))
    cluster_med = np.random.normal(loc=[20.0, 1.5], scale=0.5, size=(30, 2))
    cluster_high = np.random.normal(loc=[35.0, 3.5], scale=0.5, size=(30, 2))

    X = np.vstack([cluster_low, cluster_med, cluster_high])

    km = MarketKMeansClustering(k=3, max_iters=30, random_state=42)
    labels = km.fit_predict(X)

    assert len(labels) == 90
    assert len(np.unique(labels)) == 3
    assert km.distortion_history[-1] <= km.distortion_history[0]  # Monotonia comprovada
