"""Deterministic data reconciliation agent.

Compares observations across distinct sources for matching dates, assets and units.
Records exact residuals and explicitly documented events. Never infers dividends,
splits or adjustments to force reconciliation, and never imputes missing prices.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ObservationRecord(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    ticker: str = Field(min_length=1)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    price: float
    volume: float | None = None
    unit: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_positive_price(self):
        if self.price <= 0:
            raise ValueError("price_must_be_positive")
        return self


class EventDocument(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    ticker: str = Field(min_length=1)
    event_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    event_type: Literal["DIVIDEND", "JCP", "SPLIT", "SUBSCRIPTION"]
    cash_amount: float = Field(default=0.0, ge=0.0)
    split_ratio: float = Field(default=1.0, gt=0.0)
    document_ref: str = Field(min_length=1)
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_split_ratio(self):
        if self.split_ratio <= 0:
            raise ValueError("split_ratio_must_be_positive")
        return self



class ReconciliationItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    ticker: str
    date: str
    price_a: float | None = None
    price_b: float | None = None
    price_delta: float | None = None
    documented_adjustments: float = 0.0
    matched_events: list[EventDocument] = Field(default_factory=list)
    residual_delta: float | None = None
    status: Literal["EXACT_MATCH", "DOCUMENTED_MATCH", "UNEXPLAINED_MISMATCH", "MISSING_DATA"]
    reason: str | None = None


class ReconciliationReport(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    ticker: str
    source_a_ref: str
    source_b_ref: str
    total_dates: int
    exact_matches: int
    documented_matches: int
    unexplained_mismatches: int
    missing_data_count: int
    max_absolute_residual: float
    items: list[ReconciliationItem]
    status: Literal["RECONCILED", "DISCREPANCY_DETECTED", "FAILED"]


class DataReconciliationAgent:
    """Audited reconciliation between two market data feeds."""

    def __init__(self, tolerance: float = 0.0001):
        if tolerance < 0:
            raise ValueError("tolerance_must_be_non_negative")
        self.tolerance = tolerance

    def reconcile(
        self,
        series_a: list[ObservationRecord],
        series_b: list[ObservationRecord],
        events: list[EventDocument] | None = None,
    ) -> ReconciliationReport:
        if not series_a and not series_b:
            raise ValueError("empty_series")

        all_records = series_a + series_b
        tickers = {r.ticker for r in all_records}
        if len(tickers) > 1:
            raise ValueError(f"mixed_tickers_found: {tickers}")
        ticker = next(iter(tickers))

        units_a = {r.unit for r in series_a}
        units_b = {r.unit for r in series_b}
        if units_a and units_b and units_a != units_b:
            raise ValueError(f"unit_mismatch: {units_a} vs {units_b}")

        source_a_ref = series_a[0].source_ref if series_a else "UNAVAILABLE"
        source_b_ref = series_b[0].source_ref if series_b else "UNAVAILABLE"

        map_a = {r.date: r for r in series_a}
        map_b = {r.date: r for r in series_b}

        # Index documented corporate events strictly by (date, ticker)
        events_by_date: dict[str, list[EventDocument]] = {}
        if events:
            for ev in events:
                if ev.ticker != ticker:
                    continue
                events_by_date.setdefault(ev.event_date, []).append(ev)

        all_dates = sorted(set(map_a.keys()) | set(map_b.keys()))

        items: list[ReconciliationItem] = []
        exact_matches = 0
        documented_matches = 0
        unexplained_mismatches = 0
        missing_data_count = 0
        max_abs_residual = 0.0

        for dt in all_dates:
            rec_a = map_a.get(dt)
            rec_b = map_b.get(dt)

            if rec_a is None or rec_b is None:
                missing_data_count += 1
                missing_side = "source_a" if rec_a is None else "source_b"
                items.append(
                    ReconciliationItem(
                        ticker=ticker,
                        date=dt,
                        price_a=rec_a.price if rec_a else None,
                        price_b=rec_b.price if rec_b else None,
                        price_delta=None,
                        documented_adjustments=0.0,
                        matched_events=[],
                        residual_delta=None,
                        status="MISSING_DATA",
                        reason=f"missing_in_{missing_side}",
                    )
                )
                continue

            delta = round(rec_b.price - rec_a.price, 6)
            matched_evs = events_by_date.get(dt, [])

            # Multiplicative split adjustments and additive cash adjustments
            split_factor = 1.0
            for ev in matched_evs:
                if ev.event_type == "SPLIT":
                    split_factor *= ev.split_ratio

            expected_b = round(rec_a.price / split_factor, 6)
            split_adj = round(abs(rec_a.price - expected_b), 6)
            cash_adj = sum(round(ev.cash_amount, 6) for ev in matched_evs)
            doc_adj = round(split_adj + cash_adj, 6)

            price_diff = round(abs(rec_b.price - expected_b), 6)
            if cash_adj > 0:
                residual = round(abs(price_diff - cash_adj), 6)
            else:
                residual = price_diff

            if residual > max_abs_residual:
                max_abs_residual = residual

            if residual <= self.tolerance:
                if doc_adj > 0:
                    documented_matches += 1
                    status = "DOCUMENTED_MATCH"
                    reason = f"reconciled_with_{len(matched_evs)}_documented_events"
                else:
                    exact_matches += 1
                    status = "EXACT_MATCH"
                    reason = None
            else:
                unexplained_mismatches += 1
                status = "UNEXPLAINED_MISMATCH"
                reason = f"residual_{residual}_exceeds_tolerance_{self.tolerance}"

            items.append(
                ReconciliationItem(
                    ticker=ticker,
                    date=dt,
                    price_a=rec_a.price,
                    price_b=rec_b.price,
                    price_delta=delta,
                    documented_adjustments=doc_adj,
                    matched_events=matched_evs,
                    residual_delta=residual,
                    status=status,
                    reason=reason,
                )
            )

        overall_status: Literal["RECONCILED", "DISCREPANCY_DETECTED", "FAILED"]
        if unexplained_mismatches == 0 and missing_data_count == 0:
            overall_status = "RECONCILED"
        elif unexplained_mismatches > 0 or missing_data_count > 0:
            overall_status = "DISCREPANCY_DETECTED"
        else:
            overall_status = "FAILED"

        return ReconciliationReport(
            ticker=ticker,
            source_a_ref=source_a_ref,
            source_b_ref=source_b_ref,
            total_dates=len(all_dates),
            exact_matches=exact_matches,
            documented_matches=documented_matches,
            unexplained_mismatches=unexplained_mismatches,
            missing_data_count=missing_data_count,
            max_absolute_residual=max_abs_residual,
            items=items,
            status=overall_status,
        )
