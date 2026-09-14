"""
Testes unitarios para o Motor de PCA e Rastreamento de Fatores de Mercado — Orion Quant
Baseado no Stanford CS229 (Capitulo 12 — Principal Components Analysis)
"""
import numpy as np
import pandas as pd
import pytest
from trading_bot.data.quant.market_pca import MarketPCAEngine


def test_pca_initialization():
    pca = MarketPCAEngine(n_components=2)
    assert pca.n_components == 2
    assert pca.components_ is None


def test_pca_dimensionality_reduction_and_variance():
    """
    Testa decomposicao espectral da matriz de covariancia (CS229 Cap 12).
    """
    np.random.seed(42)
    # Simula 5 ativos correlacionados atraves de 1 fator comum de mercado forte
    n_samples = 100
    market_factor = np.random.normal(0, 1, n_samples)
    returns = np.column_stack([
        market_factor * 0.9 + np.random.normal(0, 0.1, n_samples),
        market_factor * 0.8 + np.random.normal(0, 0.15, n_samples),
        market_factor * 0.85 + np.random.normal(0, 0.12, n_samples),
        market_factor * 0.7 + np.random.normal(0, 0.2, n_samples),
        market_factor * 0.75 + np.random.normal(0, 0.18, n_samples),
    ])

    pca = MarketPCAEngine(n_components=2)
    transformed = pca.fit_transform(returns)

    assert transformed.shape == (n_samples, 2)
    assert len(pca.explained_variance_ratio_) == 2
    # O primeiro componente principal deve capturar a vasta maioria da variancia (> 75%)
    assert pca.explained_variance_ratio_[0] > 0.75
    # A soma da variancia explicada dos 2 componentes deve ser maior que o primeiro isolado
    assert np.sum(pca.explained_variance_ratio_) > pca.explained_variance_ratio_[0]
