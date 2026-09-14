"""Unit tests for ModelEvaluationAgent.

Validates walk-forward temporal splits, zero lookahead leakage,
transaction cost deductions, and faithful preservation of negative results.
"""
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
)
from trading_bot.data.quant.neural_engine import MLPFromScratch
from trading_bot.data.quant.regularized_logistic import RegularizedLogisticRegression
from scripts.evaluate_research_models import (
    build_research_dataset,
    evaluate_all_research_models,
    verify_data_approvals_fail_closed,
    verify_temporal_leakage_rejection,
)

DATASET_HASH = "d" * 64


class MockLinearModel:
    """Mock model that tracks training data to verify zero lookahead leakage."""

    def __init__(self, name="MockLinear"):
        self.name = name
        self.version = "v1.0.0-test"
        self.fitted_X = None
        self.weights = None

    def fit(self, X: np.ndarray, y: np.ndarray):
        self.fitted_X = X.copy()
        # Analytical OLS: w = (X^T X)^-1 X^T y
        XtX = X.T @ X + 1e-4 * np.eye(X.shape[1])
        self.weights = np.linalg.inv(XtX) @ X.T @ y

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.weights is None:
            return np.zeros(len(X))
        return X @ self.weights


def generate_synthetic_dataset(n_points=60):
    """Generate chronological synthetic data points with known slope."""
    points = []
    base_price = 30.0
    for i in range(n_points):
        month = 1 + (i // 20)
        day = 1 + (i % 20)
        dt_str = f"2026-{month:02d}-{day:02d}"
        f1 = float(i) / 10.0
        target = 0.5 * f1 + 0.1 * (i % 3 - 1)
        base_price += target * 0.5
        points.append(
            DataPoint(
                date=dt_str,
                features=[f1, 1.0],
                target=target,
                price=round(base_price, 2),
            )
        )
    return points


@pytest.fixture
def valid_splits():
    return SplitDates(
        train_start="2026-01-01",
        train_end="2026-01-20",
        val_start="2026-02-01",
        val_end="2026-02-20",
        test_start="2026-03-01",
        test_end="2026-03-20",
    )


def test_temporal_overlap_raises_error():
    with pytest.raises(ValueError, match="temporal_leakage_detected"):
        SplitDates(
            train_start="2026-01-01",
            train_end="2026-02-15",  # Overlaps with val_start!
            val_start="2026-02-01",
            val_end="2026-02-28",
            test_start="2026-03-01",
            test_end="2026-03-31",
        )


def test_model_fitted_exclusively_on_train_split(valid_splits):
    dataset = generate_synthetic_dataset(60)
    model = MockLinearModel()
    agent = ModelEvaluationAgent(cost_per_trade_bps=5.0)

    report = agent.evaluate(
        model=model,
        dataset=dataset,
        splits=valid_splits,
        dataset_ref="test_series.parquet",
        dataset_sha256=DATASET_HASH,
    )

    # Train period has 20 points (January)
    assert model.fitted_X is not None
    assert len(model.fitted_X) == 20
    assert report.train_metrics.sample_size == 20
    assert report.val_metrics.sample_size == 20
    assert report.test_metrics.sample_size == 20


def test_evaluation_preserves_negative_and_poor_returns(valid_splits):
    """Verify that underperforming models are faithfully recorded without filtering."""
    dataset = generate_synthetic_dataset(60)

    class ConstantLosingModel:
        name = "AlwaysShortRisingAsset"
        version = "v0.1-negative"

        def fit(self, X, y):
            pass

        def predict(self, X):
            # Predicts -1 on an asset whose price is rising -> loses money
            return -np.ones(len(X))

    agent = ModelEvaluationAgent(cost_per_trade_bps=10.0)
    report = agent.evaluate(
        model=ConstantLosingModel(),
        dataset=dataset,
        splits=valid_splits,
        dataset_ref="rising_synthetic.parquet",
        dataset_sha256=DATASET_HASH,
    )

    # Strategy must show negative returns, which are faithfully recorded
    assert report.test_metrics.strategy_return_net < 0.0
    assert report.test_metrics.excess_return < 0.0
    # Benchmark must be positive because price rose
    assert report.test_metrics.benchmark_return > 0.0


def test_transaction_costs_reduce_net_returns(valid_splits):
    dataset = generate_synthetic_dataset(60)

    class AlternatingSignModel:
        name = "AlternatingModel"

        def fit(self, X, y):
            pass

        def predict(self, X):
            return np.array([1.0 if i % 2 == 0 else -1.0 for i in range(len(X))])

    agent_cheap = ModelEvaluationAgent(cost_per_trade_bps=0.0)
    agent_costly = ModelEvaluationAgent(cost_per_trade_bps=50.0)

    report_cheap = agent_cheap.evaluate(AlternatingSignModel(), dataset, valid_splits, "ref.pqt", DATASET_HASH)
    report_costly = agent_costly.evaluate(AlternatingSignModel(), dataset, valid_splits, "ref.pqt", DATASET_HASH)

    assert report_cheap.test_metrics.strategy_return_net > report_costly.test_metrics.strategy_return_net
    assert report_costly.test_metrics.transaction_costs_paid > 0.0


def test_research_report_never_approves_for_live_signals(valid_splits):
    dataset = generate_synthetic_dataset(60)
    model = MockLinearModel()
    agent = ModelEvaluationAgent()

    report = agent.evaluate(model, dataset, valid_splits, "ref.pqt", DATASET_HASH)

    assert report.is_approved_for_signals is False
    assert any("Research-grade" in lim for lim in report.limitations)


def test_mlp_from_scratch_predict_method():
    """Verify that MLPFromScratch.predict and predict_proba behave correctly."""
    np.random.seed(42)
    mlp = MLPFromScratch(layer_dims=[3, 6, 1], learning_rate=0.05)
    X = np.array([[0.1, 0.2, 0.3], [0.8, 0.7, 0.9], [-0.5, 0.0, 0.5]])

    # 1. Probabilities
    probs = mlp.predict_proba(X)
    assert probs.shape == (3, 1)
    assert np.all(probs >= 0.0) and np.all(probs <= 1.0)

    # 2. Predictions with default threshold (0.5)
    preds_default = mlp.predict(X)
    assert preds_default.shape == (3,)
    assert set(np.unique(preds_default)).issubset({0.0, 1.0})

    # 3. Predictions with extreme thresholds
    preds_zeros = mlp.predict(X, threshold=1.1)
    np.testing.assert_array_equal(preds_zeros, np.zeros(3))

    preds_ones = mlp.predict(X, threshold=-0.1)
    np.testing.assert_array_equal(preds_ones, np.ones(3))

    # 4. 1D target in fit
    y_1d = np.array([1.0, 0.0, 1.0])
    losses = mlp.fit(X, y_1d, epochs=10)
    assert len(losses) == 10
    assert not np.isnan(losses[-1])


def test_mlp_from_scratch_walk_forward_evaluation(valid_splits):
    """Verify MLPFromScratch evaluated under ModelEvaluationAgent with full rigor."""
    np.random.seed(42)
    # Generate 60 points with 4 features each
    points = []
    base_price = 100.0
    for i in range(60):
        month = 1 + (i // 20)
        day = 1 + (i % 20)
        dt_str = f"2026-{month:02d}-{day:02d}"
        f0 = float(np.sin(i / 5.0))
        f1 = float(np.cos(i / 5.0))
        f2 = float(i % 3 - 1)
        f3 = float((i % 5) / 5.0)
        target = 1.0 if (f0 + f1 > 0) else 0.0
        base_price += (1.0 if target == 1.0 else -0.8) * 0.5
        points.append(
            DataPoint(
                date=dt_str,
                features=[f0, f1, f2, f3],
                target=target,
                price=round(max(10.0, base_price), 2),
            )
        )

    mlp = MLPFromScratch(layer_dims=[4, 8, 1], learning_rate=0.05, l2_lambda=1e-4)
    agent = ModelEvaluationAgent(cost_per_trade_bps=10.0)

    report = agent.evaluate(
        model=mlp,
        dataset=points,
        splits=valid_splits,
        dataset_ref="mlp_research_series.parquet",
        dataset_sha256=DATASET_HASH,
    )

    # Invariants and metrics assertions
    assert report.model_name == "MLPFromScratch"
    assert report.model_version == "v1.0.0-research"
    assert report.is_approved_for_signals is False
    assert report.train_metrics.sample_size == 20
    assert report.val_metrics.sample_size == 20
    assert report.test_metrics.sample_size == 20
    assert 0.0 <= report.train_metrics.directional_accuracy <= 1.0
    assert 0.0 <= report.test_metrics.directional_accuracy <= 1.0
    assert report.test_metrics.transaction_costs_paid >= 0.0
    assert report.test_metrics.max_drawdown >= 0.0


def test_regularized_logistic_regression_walk_forward_evaluation(valid_splits):
    """Verify RegularizedLogisticRegression evaluated under ModelEvaluationAgent."""
    points = []
    base_price = 50.0
    for i in range(60):
        month = 1 + (i // 20)
        day = 1 + (i % 20)
        dt_str = f"2026-{month:02d}-{day:02d}"
        f0 = float(i / 30.0)
        f1 = float((i % 4) - 2)
        target = 1.0 if f0 > 1.0 else 0.0
        base_price += 0.2 if target == 1.0 else -0.2
        points.append(
            DataPoint(
                date=dt_str,
                features=[f0, f1],
                target=target,
                price=round(max(5.0, base_price), 2),
            )
        )

    lr = RegularizedLogisticRegression(learning_rate=0.05, penalty="l2", C=1.0, max_iters=200)
    agent = ModelEvaluationAgent(cost_per_trade_bps=5.0)

    report = agent.evaluate(
        model=lr,
        dataset=points,
        splits=valid_splits,
        dataset_ref="logistic_test.parquet",
        dataset_sha256=DATASET_HASH,
    )

    assert report.is_approved_for_signals is False
    assert report.train_metrics.sample_size == 20
    assert report.val_metrics.sample_size == 20
    assert report.test_metrics.sample_size == 20


@pytest.mark.parametrize(
    "t_start,t_end,v_start,v_end,s_start,s_end",
    [
        # Same-day boundary leakage train_end == val_start
        ("2026-01-01", "2026-01-20", "2026-01-20", "2026-02-20", "2026-03-01", "2026-03-20"),
        # Same-day boundary leakage val_end == test_start
        ("2026-01-01", "2026-01-20", "2026-02-01", "2026-02-20", "2026-02-20", "2026-03-20"),
        # Overlapping train and val
        ("2026-01-01", "2026-02-05", "2026-02-01", "2026-02-20", "2026-03-01", "2026-03-20"),
        # Overlapping val and test
        ("2026-01-01", "2026-01-20", "2026-02-01", "2026-03-05", "2026-03-01", "2026-03-20"),
        # Inverted train internal
        ("2026-01-20", "2026-01-01", "2026-02-01", "2026-02-20", "2026-03-01", "2026-03-20"),
        # Inverted val internal
        ("2026-01-01", "2026-01-20", "2026-02-20", "2026-02-01", "2026-03-01", "2026-03-20"),
        # Inverted test internal
        ("2026-01-01", "2026-01-20", "2026-02-01", "2026-02-20", "2026-03-20", "2026-03-01"),
        # Completely inverted sequence: test before train
        ("2026-03-01", "2026-03-20", "2026-02-01", "2026-02-20", "2026-01-01", "2026-01-20"),
    ],
)
def test_temporal_leakage_comprehensive_matrix(t_start, t_end, v_start, v_end, s_start, s_end):
    """Assert all forms of temporal overlap, boundary sharing, and inversion raise ValueError."""
    with pytest.raises(ValueError, match="temporal_leakage_detected"):
        SplitDates(
            train_start=t_start,
            train_end=t_end,
            val_start=v_start,
            val_end=v_end,
            test_start=s_start,
            test_end=s_end,
        )


def test_is_approved_for_signals_strictly_rejects_true(valid_splits):
    """Schema invariant: ModelEvaluationReport must reject is_approved_for_signals=True."""
    dataset = generate_synthetic_dataset(60)
    agent = ModelEvaluationAgent()
    report = agent.evaluate(MockLinearModel(), dataset, valid_splits, "ref.pqt", DATASET_HASH)

    # Directly mutating or instantiating with True must be rejected by Pydantic
    data = report.model_dump()
    data["is_approved_for_signals"] = True

    with pytest.raises(ValidationError):
        ModelEvaluationReport(**data)


def test_multi_split_walk_forward_sequential_windows():
    """Verify multi-window walk-forward validation with zero cross-split leakage."""
    windows = [
        SplitDates(
            train_start="2025-01-01",
            train_end="2025-03-31",
            val_start="2025-04-01",
            val_end="2025-05-31",
            test_start="2025-06-01",
            test_end="2025-07-31",
        ),
        SplitDates(
            train_start="2025-03-01",
            train_end="2025-05-31",
            val_start="2025-06-01",
            val_end="2025-07-31",
            test_start="2025-08-01",
            test_end="2025-09-30",
        ),
    ]

    dataset, ds_sha = build_research_dataset(start_date="2025-01-01", n_days=300, seed=123)
    agent = ModelEvaluationAgent(cost_per_trade_bps=5.0)

    for i, splits in enumerate(windows):
        model = MockLinearModel(name=f"WalkForwardModel_Window_{i+1}")
        report = agent.evaluate(model, dataset, splits, f"series.parquet#w{i}", ds_sha)

        assert report.is_approved_for_signals is False
        assert report.train_metrics.sample_size > 0
        assert report.val_metrics.sample_size > 0
        assert report.test_metrics.sample_size > 0
        assert report.splits.train_end < report.splits.val_start < report.splits.test_start


def test_evaluate_research_models_pipeline_runner():
    """Verify the evaluate_research_models script logic end-to-end."""
    # 1. Guard checks
    verify_data_approvals_fail_closed()
    verify_temporal_leakage_rejection()

    # 2. Synthetic dataset generation (310 days covers 2025-01-01 through 2025-11-06)
    dataset, dataset_sha256 = build_research_dataset(n_days=310, seed=99)
    assert len(dataset) == 310
    assert len(dataset_sha256) == 64

    # 3. Multi-model walk-forward evaluation
    reports = evaluate_all_research_models(
        dataset=dataset,
        dataset_sha256=dataset_sha256,
        cost_per_trade_bps=10.0,
    )

    assert len(reports) == 6  # 3 models x 2 walk-forward windows
    for r in reports:
        assert r.is_approved_for_signals is False
        assert r.test_metrics.sample_size > 0
        assert r.test_metrics.transaction_costs_paid >= 0.0
        # Drawdowns are preserved
        assert r.test_metrics.max_drawdown >= 0.0


def test_data_approvals_fail_closed_contract(tmp_path):
    """Verify that verify_data_approvals_fail_closed rejects any non-empty approvals."""
    # Production config must pass
    verify_data_approvals_fail_closed(Path("config/data_approvals.json"))

    # Contaminated config must fail closed
    fake_config = tmp_path / "contaminated_approvals.json"
    fake_config.write_text(
        json.dumps({"version": 1, "approvals": [{"ticker": "PETR4", "status": "APPROVED"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Fail-closed invariant violated"):
        verify_data_approvals_fail_closed(fake_config)


def test_transaction_cost_exact_turnover_scaling(valid_splits):
    """Verify that transaction costs scale proportionally to turnover and cost bps."""
    dataset = generate_synthetic_dataset(60)

    class ConstantPositionModel:
        name = "BuyAndHoldModel"

        def fit(self, X, y):
            pass

        def predict(self, X):
            return np.ones(len(X))  # Constant long: 0 turnover after initial entry

    agent_low = ModelEvaluationAgent(cost_per_trade_bps=5.0)
    agent_high = ModelEvaluationAgent(cost_per_trade_bps=50.0)

    r_low = agent_low.evaluate(ConstantPositionModel(), dataset, valid_splits, "ref.pqt", DATASET_HASH)
    r_high = agent_high.evaluate(ConstantPositionModel(), dataset, valid_splits, "ref.pqt", DATASET_HASH)

    # Initial position change from 0 to 1 turnover incurs 1 step cost
    assert r_low.test_metrics.transaction_costs_paid == round(1.0 * (5.0 / 10000.0), 6)
    assert r_high.test_metrics.transaction_costs_paid == round(1.0 * (50.0 / 10000.0), 6)
    assert r_high.test_metrics.transaction_costs_paid > r_low.test_metrics.transaction_costs_paid
