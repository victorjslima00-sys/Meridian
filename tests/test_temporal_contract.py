"""
Testes Unitários e de Integração — Contrato Temporal e Higiene de Modelos (Atlas / Pesquisa)
===========================================================================================
Validação estrita:
  1. TemporalFeatureScaler: ajuste exclusivo em treino (sem contaminação out-of-sample).
  2. PointInTimeFeatureExtractor: invariância causal (futuro não altera features passadas).
  3. Dedução de custos transacionais da B3 e impacto sobre retornos líquidos e drawdowns.
  4. Preservação fidedigna de retornos e excess returns negativos (sem censura de perdas).
  5. Ingestão de séries históricas B3 COTAHIST auditadas com verificação de manifesto.
  6. Demarcação obrigatória de séries sintéticas (SYNTHETIC_TEST_ONLY) e bloqueio definitivo
     de aprovação de sinais (is_approved_for_signals == False).
"""
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from trading_bot.data.model_evaluation import (
    DataPoint,
    ModelEvaluationAgent,
    ModelEvaluationReport,
    SplitDates,
    TemporalFeatureScaler,
)
from trading_bot.data.cotahist_loader import (
    PointInTimeFeatureExtractor,
    load_b3_research_series_from_cotahist,
)


class ConstantModel:
    """Modelo dummy que sempre prevê um sinal constante."""

    def __init__(self, const_pred: float = 1.0):
        self.name = "ConstantModel"
        self.version = "v1.0.0-test"
        self.const_pred = const_pred

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        pass

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.full(len(X), self.const_pred)


def _make_dummy_datapoints(n: int = 50, trend: float = 0.01) -> list[DataPoint]:
    """Cria sequência de DataPoints cronológicos."""
    points = []
    price = 30.0
    for i in range(n):
        month = 1 + (i // 25)
        day = 1 + (i % 25)
        dt = f"2026-{month:02d}-{day:02d}"
        f1 = float(i) * 0.1
        f2 = float(np.sin(i / 5.0))
        target = 1.0 if (i % 2 == 0) else 0.0
        price *= (1.0 + trend)
        points.append(
            DataPoint(
                date=dt,
                features=[round(f1, 4), round(f2, 4)],
                target=target,
                price=round(price, 4),
            )
        )
    return points


def test_temporal_feature_scaler_fits_strictly_on_train():
    """Garante que o scaler computa média e desvio padrão exclusivamente do treino."""
    X_train = np.array([[10.0, 100.0], [20.0, 200.0], [30.0, 300.0]])
    X_val = np.array([[50.0, 500.0]])
    X_test = np.array([[100.0, 1000.0]])

    scaler = TemporalFeatureScaler()
    scaler.fit(X_train)

    expected_mean = np.array([20.0, 200.0])
    expected_std = np.std(X_train, axis=0)

    np.testing.assert_allclose(scaler.mean_, expected_mean)
    np.testing.assert_allclose(scaler.scale_, expected_std)

    # Val e Test são transformados com a média e escala do treino
    val_trans = scaler.transform(X_val)
    expected_val = (X_val - expected_mean) / expected_std
    np.testing.assert_allclose(val_trans, expected_val)

    test_trans = scaler.transform(X_test)
    expected_test = (X_test - expected_mean) / expected_std
    np.testing.assert_allclose(test_trans, expected_test)


def test_temporal_feature_scaler_guardrails():
    """Valida salvaguardas de uso indevido do scaler."""
    scaler = TemporalFeatureScaler()
    with pytest.raises(RuntimeError, match="scaler_not_fitted"):
        scaler.transform(np.array([[1.0, 2.0]]))

    with pytest.raises(ValueError, match="cannot_fit_empty_array"):
        scaler.fit(np.array([]))


def test_point_in_time_feature_extractor_causal_invariance():
    """
    Teorema de Causalidade Temporal:
    Alterar preços futuros a partir do dia K NÃO pode alterar nenhuma feature antes de K.
    """
    rng = np.random.default_rng(42)
    n = 60
    prices = 20.0 + np.cumsum(rng.normal(0, 0.5, n))
    prices = np.maximum(1.0, prices)

    # Extrai features no dataset original
    X_orig, y_orig = PointInTimeFeatureExtractor.extract_causal_features(prices, warmup_bars=20)

    # Cria mutação violenta no futuro (após o índice 40)
    prices_mutated = prices.copy()
    prices_mutated[40:] += 100.0  # Choque de preço artificial no futuro

    X_mut, y_mut = PointInTimeFeatureExtractor.extract_causal_features(prices_mutated, warmup_bars=20)

    # Índices de 20 a 39 correspondem às linhas 0 a 19 de X
    # Para todas as linhas antes da mutação, as features DEVEM ser estritamente idênticas
    np.testing.assert_allclose(
        X_orig[:19],
        X_mut[:19],
        err_msg="Vazamento de informação futura detectado! Features passadas foram alteradas por dados futuros.",
    )


def test_b3_transaction_costs_deduction():
    """Valida que o desconto de custos B3 (bps) reduz o retorno e aumenta custos pagos."""
    points = _make_dummy_datapoints(n=50, trend=0.01)
    splits = SplitDates(
        train_start="2026-01-01",
        train_end="2026-01-15",
        val_start="2026-01-16",
        val_end="2026-01-22",
        test_start="2026-01-23",
        test_end="2026-02-25",
    )

    model = ConstantModel(const_pred=1.0)  # Always LONG

    agent_free = ModelEvaluationAgent(cost_per_trade_bps=0.0)
    rep_free = agent_free.evaluate(model, points, splits, "ref.pqt", "0" * 64)

    agent_costly = ModelEvaluationAgent(cost_per_trade_bps=20.0)  # 20 bps
    rep_costly = agent_costly.evaluate(model, points, splits, "ref.pqt", "0" * 64)

    assert rep_free.test_metrics.transaction_costs_paid == 0.0
    assert rep_costly.test_metrics.transaction_costs_paid > 0.0
    assert rep_costly.test_metrics.strategy_return_net < rep_free.test_metrics.strategy_return_net


def test_faithful_preservation_of_negative_returns_and_drawdowns():
    """Garante que retornos e excess returns negativos são preservados fielmente sem censura."""
    # Série em queda contínua
    points = _make_dummy_datapoints(n=50, trend=-0.02)
    splits = SplitDates(
        train_start="2026-01-01",
        train_end="2026-01-15",
        val_start="2026-01-16",
        val_end="2026-01-22",
        test_start="2026-01-23",
        test_end="2026-02-25",
    )

    # Modelo comprado na queda
    model = ConstantModel(const_pred=1.0)
    agent = ModelEvaluationAgent(cost_per_trade_bps=10.0)
    rep = agent.evaluate(model, points, splits, "bear_series.pqt", "1" * 64)

    assert rep.test_metrics.strategy_return_net < 0.0
    assert rep.test_metrics.max_drawdown > 0.0
    # Resultados negativos não são censurados
    assert rep.train_metrics.sample_size > 0
    assert rep.test_metrics.sample_size > 0


def test_cotahist_loader_with_fixture_integrity(tmp_path):
    """Valida carga ponta a ponta de exportação COTAHIST com manifesto SHA-256 e features causais."""
    export_dir = tmp_path / "cotahist_export_test"
    export_dir.mkdir()

    # Gera quotes.csv com 30 cotações sintéticas do layout
    quotes_csv = export_dir / "quotes.csv"
    with quotes_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "trading_date", "ticker", "market", "bdi", "issuer", "specification",
                "currency", "open", "high", "low", "mean", "close", "bid", "ask",
                "trades", "quantity", "financial_volume", "quotation_factor",
                "isin", "distribution", "quality_flags",
            ],
        )
        writer.writeheader()
        base_p = 30.0
        for i in range(35):
            day = 1 + (i % 28)
            month = 1 + (i // 28)
            base_p += (i % 3 - 1) * 0.5
            writer.writerow({
                "trading_date": f"2026-{month:02d}-{day:02d}",
                "ticker": "PETR4",
                "market": 10,
                "bdi": "02",
                "issuer": "PETROBRAS",
                "specification": "PN",
                "currency": "R$",
                "open": f"{base_p - 0.2:.2f}",
                "high": f"{base_p + 0.5:.2f}",
                "low": f"{base_p - 0.5:.2f}",
                "mean": f"{base_p:.2f}",
                "close": f"{base_p:.2f}",
                "bid": f"{base_p - 0.1:.2f}",
                "ask": f"{base_p + 0.1:.2f}",
                "trades": 100,
                "quantity": 1000,
                "financial_volume": f"{base_p * 1000:.2f}",
                "quotation_factor": 1,
                "isin": "BRPETRACNPR6",
                "distribution": 100,
                "quality_flags": "",
            })

    # Cria manifesto válido
    manifest_data = {
        "source_url_declared": "https://www.b3.com.br/cotahist",
        "structural_validation": "passed",
        "first_date": "2026-01-01",
        "last_date": "2026-02-07",
    }
    (export_dir / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    # Carrega via loader
    points, quotes_hash, dataset_ref = load_b3_research_series_from_cotahist(
        export_dir=export_dir,
        ticker="PETR4",
        warmup_bars=20,
    )

    assert len(points) == 15  # 35 total - 20 warmup
    assert len(quotes_hash) == 64
    assert "PETR4" in dataset_ref
    assert points[0].price > 0.0
    assert len(points[0].features) == 4

    # Testa rejeição fail-closed se manifesto falhar
    manifest_data["structural_validation"] = "failed"
    (export_dir / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ValueError, match="cotahist_integrity_failed"):
        load_b3_research_series_from_cotahist(export_dir=export_dir, ticker="PETR4")


def test_synthetic_dataset_demarcation_and_non_approval():
    """Valida que datasets sintéticos são explicitamente identificados e rejeitam aprovação."""
    points = _make_dummy_datapoints(n=50)
    splits = SplitDates(
        train_start="2026-01-01",
        train_end="2026-01-15",
        val_start="2026-01-16",
        val_end="2026-01-22",
        test_start="2026-01-23",
        test_end="2026-02-25",
    )

    agent = ModelEvaluationAgent()
    rep = agent.evaluate(
        model=ConstantModel(),
        dataset=points,
        splits=splits,
        dataset_ref="synthetic_test.pqt",
        dataset_sha256="a" * 64,
        dataset_kind="SYNTHETIC_TEST_ONLY",
        scale_features=True,
    )

    assert rep.dataset_kind == "SYNTHETIC_TEST_ONLY"
    assert rep.is_synthetic_fixture is True
    assert rep.is_real_market_evidence is False
    assert rep.is_approved_for_signals is False
    assert "Série sintética" in rep.disclaimer

    # Proibição estrutural: Pydantic rejeita is_approved_for_signals=True
    data = rep.model_dump()
    data["is_approved_for_signals"] = True
    with pytest.raises(ValidationError):
        ModelEvaluationReport(**data)