#!/usr/bin/env python3
"""Standardized Quantitative Research Model Walk-Forward Evaluation Runner.

Enforces strict temporal ordering ($Train_{end} < Val_{start} < Test_{start}$) with
zero lookahead bias. Fits estimators exclusively on the training split, deducts
turnover-scaled transaction costs and slippage, benchmarks against buy-and-hold,
faithfully preserves negative returns without artificial suppression, and guarantees
that `is_approved_for_signals` remains permanently False.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from trading_bot.data.model_evaluation import (
    DataPoint,
    DatasetKind,
    ModelEvaluationAgent,
    ModelEvaluationReport,
    SplitDates,
    TemporalFeatureScaler,
)
from trading_bot.data.cotahist_loader import (
    PointInTimeFeatureExtractor,
    load_b3_research_series_from_cotahist,
)
from trading_bot.data.quant.neural_engine import MLPFromScratch
from trading_bot.data.quant.regularized_logistic import RegularizedLogisticRegression

logger = logging.getLogger("evaluate_research_models")


class LinearBenchmarkModel:
    """Ordinary least squares baseline model with L2 regularization."""

    def __init__(self, name: str = "LinearRegressionBaseline"):
        self.name = name
        self.version = "v1.0.0-research"
        self.weights: Optional[np.ndarray] = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> LinearBenchmarkModel:
        """Analytical ridge solution: w = (X^T X + lambda I)^-1 X^T y."""
        X_b = np.hstack([np.ones((X.shape[0], 1)), X])
        d = X_b.shape[1]
        ridge_eye = 1e-3 * np.eye(d)
        ridge_eye[0, 0] = 0.0  # Do not regularize intercept
        self.weights = np.linalg.inv(X_b.T @ X_b + ridge_eye) @ X_b.T @ y
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.weights is None:
            return np.zeros(X.shape[0])
        X_b = np.hstack([np.ones((X.shape[0], 1)), X])
        return X_b @ self.weights


def verify_data_approvals_fail_closed(config_path: Path = Path("config/data_approvals.json")) -> None:
    """Verify that production data approvals registry remains fail-closed."""
    if not config_path.is_absolute():
        config_path = REPO_ROOT / config_path
    if not config_path.exists():
        raise FileNotFoundError(f"Approvals configuration not found at: {config_path}")

    content = json.loads(config_path.read_text(encoding="utf-8"))
    version = content.get("version")
    approvals = content.get("approvals")

    if version != 1 or not isinstance(approvals, list) or len(approvals) != 0:
        raise ValueError(
            f"Fail-closed invariant violated in {config_path}: "
            f"expected {{'version': 1, 'approvals': []}}, got {content}"
        )
    logger.info("Verified config/data_approvals.json is intact and fail-closed: %s", content)


def verify_temporal_leakage_rejection() -> None:
    """Demonstrate that overlapping, inverted, or contiguous-boundary splits are rejected."""
    # 1. Overlap between train and validation
    try:
        SplitDates(
            train_start="2025-01-01",
            train_end="2025-03-15",
            val_start="2025-03-01",
            val_end="2025-04-30",
            test_start="2025-05-01",
            test_end="2025-06-30",
        )
        raise AssertionError("Expected ValueError on overlapping train and val splits!")
    except ValueError as e:
        if "temporal_leakage_detected" not in str(e):
            raise AssertionError(f"Unexpected error message: {e}") from e

    # 2. Same-day boundary leakage (train_end == val_start)
    try:
        SplitDates(
            train_start="2025-01-01",
            train_end="2025-03-31",
            val_start="2025-03-31",
            val_end="2025-04-30",
            test_start="2025-05-01",
            test_end="2025-06-30",
        )
        raise AssertionError("Expected ValueError on same-day boundary leakage!")
    except ValueError as e:
        if "temporal_leakage_detected" not in str(e):
            raise AssertionError(f"Unexpected error message: {e}") from e

    # 3. Inversion between val and test (val_end >= test_start)
    try:
        SplitDates(
            train_start="2025-01-01",
            train_end="2025-02-28",
            val_start="2025-03-01",
            val_end="2025-05-15",
            test_start="2025-05-01",
            test_end="2025-06-30",
        )
        raise AssertionError("Expected ValueError on inverted val and test splits!")
    except ValueError as e:
        if "temporal_leakage_detected" not in str(e):
            raise AssertionError(f"Unexpected error message: {e}") from e

    logger.info("Verified zero lookahead leakage: temporal overlap and inversion strictly rejected.")


def build_research_dataset(
    start_date: str = "2025-01-01",
    n_days: int = 300,
    seed: int = 42,
) -> Tuple[List[DataPoint], str]:
    """Generate a deterministic multi-feature chronological dataset.

    Returns:
        points: list of DataPoint objects.
        dataset_sha256: SHA-256 digest of the raw serialized records.
    """
    rng = np.random.default_rng(seed)
    current_date = date.fromisoformat(start_date)

    base_price = 50.0
    points: List[DataPoint] = []
    hasher = hashlib.sha256()

    for i in range(n_days):
        dt_str = current_date.isoformat()

        # Non-linear synthetic market features
        f0 = float(rng.standard_normal())                 # Short-term return momentum
        f1 = float(np.sin(i / 15.0) + rng.normal(0, 0.2))  # Medium-term cyclic oscillation
        f2 = float(np.cos(i / 30.0) + rng.normal(0, 0.2))  # Macro trend regime indicator
        f3 = float(rng.uniform(-1.0, 1.0))                 # Microstructure flow imbalance

        # Latent non-linear market target
        latent = 0.4 * f0 + 0.3 * f1 - 0.2 * f2 + 0.1 * f3 + rng.normal(0, 0.1)
        target = 1.0 if latent > 0.0 else 0.0

        # Price update based on latent return
        day_return = 0.015 * np.tanh(latent)
        base_price = max(1.0, base_price * (1.0 + day_return))

        dp = DataPoint(
            date=dt_str,
            features=[round(f0, 6), round(f1, 6), round(f2, 6), round(f3, 6)],
            target=round(target, 4),
            price=round(base_price, 4),
        )
        points.append(dp)
        hasher.update(f"{dt_str}:{dp.features}:{dp.target}:{dp.price}\n".encode("utf-8"))

        current_date += timedelta(days=1)

    dataset_sha256 = hasher.hexdigest()
    return points, dataset_sha256


def get_default_walk_forward_windows() -> List[Tuple[str, SplitDates]]:
    """Return standard sequentially disjoint walk-forward splits."""
    return [
        (
            "Window_1",
            SplitDates(
                train_start="2025-01-01",
                train_end="2025-04-30",
                val_start="2025-05-01",
                val_end="2025-06-30",
                test_start="2025-07-01",
                test_end="2025-08-31",
            ),
        ),
        (
            "Window_2",
            SplitDates(
                train_start="2025-03-01",
                train_end="2025-06-30",
                val_start="2025-07-01",
                val_end="2025-08-31",
                test_start="2025-09-01",
                test_end="2025-10-27",
            ),
        ),
    ]


def evaluate_all_research_models(
    dataset: List[DataPoint],
    dataset_sha256: str,
    dataset_ref: str = "synthetic_b3_research_series.parquet",
    windows: Optional[List[Tuple[str, SplitDates]]] = None,
    cost_per_trade_bps: float = 10.0,
    dataset_kind: DatasetKind = "SYNTHETIC_TEST_ONLY",
    scale_features: bool = True,
) -> List[ModelEvaluationReport]:
    """Evaluate candidate quantitative predictive models under ModelEvaluationAgent."""
    if windows is None:
        windows = get_default_walk_forward_windows()

    agent = ModelEvaluationAgent(cost_per_trade_bps=cost_per_trade_bps)
    reports: List[ModelEvaluationReport] = []

    for window_name, splits in windows:
        logger.info("Evaluating Walk-Forward Split: %s (%s -> %s)", window_name, splits.train_start, splits.test_end)

        # 1. Neural Engine Deep MLP
        mlp = MLPFromScratch(layer_dims=[4, 8, 1], learning_rate=0.05, l2_lambda=1e-4)
        mlp_report = agent.evaluate(
            model=mlp,
            dataset=dataset,
            splits=splits,
            dataset_ref=f"{dataset_ref}#{window_name}",
            dataset_sha256=dataset_sha256,
            dataset_kind=dataset_kind,
            scale_features=scale_features,
        )
        reports.append(mlp_report)

        # 2. Regularized Logistic Regression
        lr = RegularizedLogisticRegression(learning_rate=0.05, penalty="l2", C=1.0, max_iters=300)
        lr.name = "RegularizedLogisticRegression"
        lr.version = "v1.0.0-research"
        lr_report = agent.evaluate(
            model=lr,
            dataset=dataset,
            splits=splits,
            dataset_ref=f"{dataset_ref}#{window_name}",
            dataset_sha256=dataset_sha256,
            dataset_kind=dataset_kind,
            scale_features=scale_features,
        )
        reports.append(lr_report)

        # 3. Linear Regression Baseline
        lin = LinearBenchmarkModel()
        lin_report = agent.evaluate(
            model=lin,
            dataset=dataset,
            splits=splits,
            dataset_ref=f"{dataset_ref}#{window_name}",
            dataset_sha256=dataset_sha256,
            dataset_kind=dataset_kind,
            scale_features=scale_features,
        )
        reports.append(lin_report)

    # Permanent Invariant Assertion
    for r in reports:
        if r.is_approved_for_signals is not False:
            raise RuntimeError(f"Invariant violated: {r.model_name} is marked as approved for signals!")

    return reports


def format_summary_table(reports: List[ModelEvaluationReport]) -> str:
    """Format evaluation reports into an ASCII summary table."""
    headers = [
        "Model",
        "Window",
        "Type",
        "Train Acc",
        "Val Acc",
        "Test Acc",
        "Test Net Ret",
        "Bench Ret",
        "Excess Ret",
        "Max DD",
        "Costs Paid",
        "Signals Approved?",
    ]
    rows = []
    for r in reports:
        window_ref = r.dataset_ref.split("#")[-1] if "#" in r.dataset_ref else "N/A"
        type_label = "SYNTHETIC" if r.is_synthetic_fixture else "B3_COTAHIST"
        rows.append([
            r.model_name,
            window_ref,
            type_label,
            f"{r.train_metrics.directional_accuracy:.2%}",
            f"{r.val_metrics.directional_accuracy:.2%}",
            f"{r.test_metrics.directional_accuracy:.2%}",
            f"{r.test_metrics.strategy_return_net:.4f}",
            f"{r.test_metrics.benchmark_return:.4f}",
            f"{r.test_metrics.excess_return:.4f}",
            f"{r.test_metrics.max_drawdown:.2%}",
            f"{r.test_metrics.transaction_costs_paid:.5f}",
            str(r.is_approved_for_signals).upper(),
        ])

    col_widths = [len(h) for h in headers]
    for row in rows:
        for idx, val in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(val))

    separator = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    header_str = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"

    lines = [separator, header_str, separator]
    for row in rows:
        row_str = "| " + " | ".join(val.ljust(col_widths[i]) for i, val in enumerate(row)) + " |"
        lines.append(row_str)
    lines.append(separator)
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Standardized Walk-Forward Quantitative Model Evaluation Runner"
    )
    parser.add_argument(
        "--cotahist-dir",
        type=Path,
        default=None,
        help="Path to audited B3 COTAHIST exported directory (containing quotes.csv and manifest.json)",
    )
    parser.add_argument(
        "--ticker",
        type=str,
        default="PETR4",
        help="Ticker to evaluate when loading COTAHIST (default: PETR4)",
    )
    parser.add_argument(
        "--cost-bps",
        type=float,
        default=10.0,
        help="Turnover transaction cost and slippage per trade in basis points (default: 10.0 B3 fees)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to save JSON model evaluation reports (optional)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=300,
        help="Number of chronological observation days to generate (default: 300)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational stdout logging",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 1. Guard check: ensure data approvals are fail-closed
    verify_data_approvals_fail_closed()

    # 2. Guard check: demonstrate temporal leakage rejection
    verify_temporal_leakage_rejection()

    windows: Optional[List[Tuple[str, SplitDates]]] = None

    if args.cotahist_dir:
        logger.info("Carregando série histórica B3 auditada de COTAHIST: %s (Ticker: %s)...", args.cotahist_dir, args.ticker)
        dataset, dataset_sha256, dataset_ref = load_b3_research_series_from_cotahist(
            export_dir=args.cotahist_dir,
            ticker=args.ticker,
        )
        dataset_kind = "B3_COTAHIST_AUDITED"
        logger.info("Série B3 carregada: %d barras válidas, SHA-256: %s", len(dataset), dataset_sha256)

        if len(dataset) >= 60:
            dates = [d.date for d in dataset]
            n = len(dates)
            t1 = int(n * 0.4)
            t2 = int(n * 0.7)
            windows = [
                (
                    "B3_WalkForward_1",
                    SplitDates(
                        train_start=dates[0],
                        train_end=dates[t1],
                        val_start=dates[t1 + 1],
                        val_end=dates[t2],
                        test_start=dates[t2 + 1],
                        test_end=dates[-1],
                    ),
                )
            ]
    else:
        logger.warning(
            "\n" + "!" * 80 + "\n"
            "ALERTA METODOLÓGICO INSTITUCIONAL (DIRETRIZ ASTRA 14/09/2026):\n"
            "O script evaluate_research_models.py está sendo executado sobre SÉRIE SINTÉTICA ESTOCÁSTICA.\n"
            "Seus resultados NÃO representam desempenho B3 e NÃO comprovam rentabilidade.\n"
            "É proibido publicar ou utilizar estes números como validação de retorno financeiro.\n"
            + "!" * 80 + "\n"
        )
        logger.info("Synthesizing %d days of chronological multi-feature research data...", args.days)
        dataset, dataset_sha256 = build_research_dataset(n_days=args.days)
        dataset_ref = "synthetic_b3_research_series.parquet"
        dataset_kind = "SYNTHETIC_TEST_ONLY"
        logger.info("Dataset generated: %d points, SHA-256: %s", len(dataset), dataset_sha256)

        if args.days < 250:
            dates = [d.date for d in dataset]
            n = len(dates)
            t1 = int(n * 0.4)
            t2 = int(n * 0.7)
            windows = [
                (
                    "Synthetic_Window_Custom",
                    SplitDates(
                        train_start=dates[0],
                        train_end=dates[t1],
                        val_start=dates[t1 + 1],
                        val_end=dates[t2],
                        test_start=dates[t2 + 1],
                        test_end=dates[-1],
                    ),
                )
            ]

    # 4. Run walk-forward model evaluations across disjoint time splits
    reports = evaluate_all_research_models(
        dataset=dataset,
        dataset_sha256=dataset_sha256,
        dataset_ref=dataset_ref,
        windows=windows,
        cost_per_trade_bps=args.cost_bps,
        dataset_kind=dataset_kind,
        scale_features=True,
    )

    # 5. Print summary report table
    print("\n" + "=" * 80)
    if dataset_kind == "SYNTHETIC_TEST_ONLY":
        print("RELATÓRIO DE AVALIAÇÃO QUANTITATIVA (SÉRIE SINTÉTICA — APENAS TESTE)")
        print("AVISO: DADOS SINTÉTICOS. NÃO CONSTITUI DESEMPENHO REAL NA B3.")
    else:
        print("RELATÓRIO DE AVALIAÇÃO QUANTITATIVA (DADOS AUDITADOS B3 COTAHIST)")
    print("=" * 80)
    print(format_summary_table(reports))
    print("\nInvariant Confirmation: is_approved_for_signals=False permanently across all models.")

    # 6. Save reports to JSON if output directory requested
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for i, report in enumerate(reports):
            clean_ref = (
                report.dataset_ref.replace("#", "_")
                .replace(".", "_")
                .replace("/", "_")
                .replace(":", "_")
            )
            filename = f"eval_{report.model_name}_{clean_ref}.json"
            out_file = args.output_dir / filename
            out_file.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Saved %d evaluation reports to %s", len(reports), args.output_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
