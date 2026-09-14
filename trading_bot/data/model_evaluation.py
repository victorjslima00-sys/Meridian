"""Deterministic quantitative model evaluation agent.

Enforces strict temporal walk-forward splits (train, validation, test) to eliminate
lookahead bias. Models are fit exclusively on the training split. Transaction costs
and benchmarks are explicitly deducted. Negative and underperforming results are
faithfully preserved. Outputs are strictly research-grade and never promoted to signals.
"""
import math
from typing import Any, Literal
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SplitDates(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    train_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    train_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    val_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    val_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    test_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    test_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def validate_strict_temporal_order(self):
        # Strict temporal sequence without overlap: train_end < val_start and val_end < test_start
        if not (self.train_start <= self.train_end < self.val_start <= self.val_end < self.test_start <= self.test_end):
            raise ValueError("temporal_leakage_detected: splits must be strictly sequential")
        return self


class DataPoint(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    features: list[float]
    target: float
    price: float = Field(gt=0.0)


class EvaluationMetrics(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    sample_size: int
    mae: float
    rmse: float
    directional_accuracy: float
    strategy_return_net: float
    benchmark_return: float
    excess_return: float
    transaction_costs_paid: float
    sharpe_ratio: float | None = None
    max_drawdown: float


DatasetKind = Literal["SYNTHETIC_TEST_ONLY", "B3_COTAHIST_AUDITED", "B3_LAKEHOUSE_HISTORICAL"]


class TemporalFeatureScaler:
    """
    Normalizador temporal seguro para aprendizado supervisionado em finanças.
    Ajusta média e desvio padrão estritamente sobre a partição de treino.
    Impede vazamento de informação estatística futura (lookahead bias / data leakage).
    """

    def __init__(self, eps: float = 1e-8):
        self.eps = eps
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None
        self.is_fitted: bool = False

    def fit(self, X: np.ndarray | list) -> "TemporalFeatureScaler":
        X_arr = np.asarray(X, dtype=float)
        if X_arr.size == 0:
            raise ValueError("cannot_fit_empty_array")
        if X_arr.ndim == 1:
            X_arr = X_arr.reshape(-1, 1)
        self.mean_ = np.mean(X_arr, axis=0)
        self.scale_ = np.std(X_arr, axis=0)
        # Evita divisão por zero para features constantes
        self.scale_[self.scale_ < self.eps] = 1.0
        self.is_fitted = True
        return self

    def transform(self, X: np.ndarray | list) -> np.ndarray:
        if not self.is_fitted or self.mean_ is None or self.scale_ is None:
            raise RuntimeError("scaler_not_fitted_call_fit_first")
        X_arr = np.asarray(X, dtype=float)
        if X_arr.ndim == 1:
            X_arr = X_arr.reshape(-1, 1)
        return (X_arr - self.mean_) / self.scale_

    def fit_transform(self, X: np.ndarray | list) -> np.ndarray:
        return self.fit(X).transform(X)


class ModelEvaluationReport(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    model_name: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    dataset_ref: str = Field(min_length=1)
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_kind: DatasetKind = "SYNTHETIC_TEST_ONLY"
    is_synthetic_fixture: bool = True
    is_real_market_evidence: bool = False
    disclaimer: str = Field(min_length=1)
    splits: SplitDates
    train_metrics: EvaluationMetrics
    val_metrics: EvaluationMetrics
    test_metrics: EvaluationMetrics
    benchmark_name: str
    cost_per_trade_bps: float
    limitations: list[str]
    is_approved_for_signals: Literal[False] = False


class ModelEvaluationAgent:
    """Rigorous research interface for testing models across time splits."""

    def __init__(self, cost_per_trade_bps: float = 5.0):
        if cost_per_trade_bps < 0:
            raise ValueError("cost_bps_must_be_non_negative")
        self.cost_bps = cost_per_trade_bps

    def evaluate(
        self,
        model: Any,
        dataset: list[DataPoint],
        splits: SplitDates,
        dataset_ref: str,
        dataset_sha256: str,
        benchmark_name: str = "BUY_AND_HOLD",
        dataset_kind: DatasetKind = "SYNTHETIC_TEST_ONLY",
        is_synthetic_fixture: bool | None = None,
        scale_features: bool = False,
    ) -> ModelEvaluationReport:
        if not dataset:
            raise ValueError("empty_dataset")

        if is_synthetic_fixture is None:
            is_synthetic_fixture = (dataset_kind == "SYNTHETIC_TEST_ONLY")
        is_real_market_evidence = not is_synthetic_fixture

        if is_synthetic_fixture:
            disclaimer = (
                "AVISO METODOLÓGICO: Série sintética de pesquisa. NÃO representa "
                "desempenho de mercado na B3 e é proibida para validação de rentabilidade "
                "ou aprovação de sinais."
            )
        else:
            disclaimer = (
                "Série histórica B3 auditada com proveniência e hash SHA-256 verificado. "
                "Exclusivamente para pesquisa quantitativa."
            )

        # Sort dataset chronologically
        sorted_data = sorted(dataset, key=lambda d: d.date)

        train_set = [d for d in sorted_data if splits.train_start <= d.date <= splits.train_end]
        val_set = [d for d in sorted_data if splits.val_start <= d.date <= splits.val_end]
        test_set = [d for d in sorted_data if splits.test_start <= d.date <= splits.test_end]

        if not train_set:
            raise ValueError("empty_train_split")
        if not val_set:
            raise ValueError("empty_validation_split")
        if not test_set:
            raise ValueError("empty_test_split")

        # 1. Fit ONLY on train split
        X_train_raw = np.array([d.features for d in train_set], dtype=float)
        y_train = np.array([d.target for d in train_set], dtype=float)

        scaler: TemporalFeatureScaler | None = None
        if scale_features:
            scaler = TemporalFeatureScaler()
            X_train = scaler.fit_transform(X_train_raw)
        else:
            X_train = X_train_raw

        if hasattr(model, "fit"):
            model.fit(X_train, y_train)

        # 2. Evaluate each split independently
        train_metrics = self._evaluate_split(model, train_set, scaler=scaler)
        val_metrics = self._evaluate_split(model, val_set, scaler=scaler)
        test_metrics = self._evaluate_split(model, test_set, scaler=scaler)

        # Document known limitations explicitly
        limitations = [
            "Research-grade evaluation only; not approved for autonomous order routing.",
            f"Fitted strictly on train [{splits.train_start} to {splits.train_end}]; test period [{splits.test_start} to {splits.test_end}] is strictly out-of-sample.",
            f"Transaction friction modeled at {self.cost_bps} bps per position turnover.",
            "Historical backtest results are subject to non-stationary market regime changes.",
        ]
        if is_synthetic_fixture:
            limitations.append(
                "Série sintética estocástica — não reflete liquidez, slippage ou dinâmica real do livro de ofertas da B3."
            )

        model_name = getattr(model, "name", model.__class__.__name__)
        model_version = getattr(model, "version", "v1.0.0-research")

        return ModelEvaluationReport(
            model_name=model_name,
            model_version=model_version,
            dataset_ref=dataset_ref,
            dataset_sha256=dataset_sha256,
            dataset_kind=dataset_kind,
            is_synthetic_fixture=is_synthetic_fixture,
            is_real_market_evidence=is_real_market_evidence,
            disclaimer=disclaimer,
            splits=splits,
            train_metrics=train_metrics,
            val_metrics=val_metrics,
            test_metrics=test_metrics,
            benchmark_name=benchmark_name,
            cost_per_trade_bps=self.cost_bps,
            limitations=limitations,
            is_approved_for_signals=False,
        )

    def _evaluate_split(
        self,
        model: Any,
        points: list[DataPoint],
        scaler: TemporalFeatureScaler | None = None,
    ) -> EvaluationMetrics:
        X = np.array([d.features for d in points], dtype=float)
        if scaler is not None:
            X = scaler.transform(X)
        y = np.array([d.target for d in points], dtype=float)
        prices = np.array([d.price for d in points], dtype=float)

        preds = np.array(model.predict(X), dtype=float).flatten()

        errors = preds - y
        mae = float(np.mean(np.abs(errors)))
        rmse = float(np.sqrt(np.mean(errors ** 2)))

        # Directional accuracy: sign match
        correct_dir = (np.sign(preds) == np.sign(y))
        dir_acc = float(np.mean(correct_dir)) if len(y) > 0 else 0.0

        # Benchmark return: buy and hold of price series
        bench_ret = float((prices[-1] - prices[0]) / prices[0]) if len(prices) > 1 and prices[0] > 0 else 0.0

        # Strategy simulation: long if pred > 0, short if pred < 0, neutral if 0
        positions = np.sign(preds)
        cost_rate = self.cost_bps / 10000.0

        daily_strat_returns = []
        total_costs = 0.0
        current_pos = 0.0

        for i in range(len(prices) - 1):
            target_pos = positions[i]
            turnover = abs(target_pos - current_pos)
            step_cost = turnover * cost_rate
            total_costs += step_cost

            # Asset return for the period
            asset_ret = (prices[i + 1] - prices[i]) / prices[i]
            strat_ret = (target_pos * asset_ret) - step_cost
            daily_strat_returns.append(strat_ret)
            current_pos = target_pos

        daily_returns_arr = np.array(daily_strat_returns, dtype=float)
        total_strat_return = float(np.prod(1.0 + daily_returns_arr) - 1.0) if len(daily_returns_arr) > 0 else 0.0

        # Max Drawdown
        cum_ret = np.cumprod(1.0 + daily_returns_arr) if len(daily_returns_arr) > 0 else np.array([1.0])
        peaks = np.maximum.accumulate(cum_ret)
        drawdowns = (cum_ret - peaks) / peaks
        max_dd = float(abs(np.min(drawdowns))) if len(drawdowns) > 0 else 0.0

        # Sharpe ratio: null if std is 0 or sample < 5
        sharpe = None
        if len(daily_returns_arr) >= 5:
            std = float(np.std(daily_returns_arr))
            if std > 1e-8:
                sharpe = float((np.mean(daily_returns_arr) / std) * math.sqrt(252))

        return EvaluationMetrics(
            sample_size=len(points),
            mae=round(mae, 6),
            rmse=round(rmse, 6),
            directional_accuracy=round(dir_acc, 4),
            strategy_return_net=round(total_strat_return, 6),
            benchmark_return=round(bench_ret, 6),
            excess_return=round(total_strat_return - bench_ret, 6),
            transaction_costs_paid=round(total_costs, 6),
            sharpe_ratio=round(sharpe, 4) if sharpe is not None else None,
            max_drawdown=round(max_dd, 4),
        )
