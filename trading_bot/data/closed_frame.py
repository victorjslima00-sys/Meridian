"""Closed Daily Signal Frame Transformation (NEXUS-004).

Donchian is a daily strategy. During live trading, current-day daily bars are
forming and incomplete. They must NEVER participate in dataset digests, approvals,
signal calculations (Donchian, SMA, RSI, volume), or macro regime evaluation.

Provides a single deterministic transformation shared across:
- MarketAnalyst
- Approval candidate builder
- Paper preflight
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime
from typing import Any, Optional, Tuple, Union
import pandas as pd

from backend.app.markets.b3_session import (
    B3_TIMEZONE,
    B3SessionPhase,
    get_session_phase,
)


@dataclass(frozen=True)
class ClosedFrameResult:
    """Audit record of closed-frame transformation."""
    df: pd.DataFrame
    market_date: datetime.date
    decision_bar_date: Optional[datetime.date]
    today_bar_removed: bool
    session_phase: B3SessionPhase
    total_bars_input: int
    total_bars_output: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_date": str(self.market_date),
            "decision_bar_date": str(self.decision_bar_date) if self.decision_bar_date else None,
            "today_bar_removed": self.today_bar_removed,
            "session_phase": self.session_phase.value,
            "total_bars_input": self.total_bars_input,
            "total_bars_output": self.total_bars_output,
        }

    @property
    def closed_df(self) -> pd.DataFrame:
        return self.df


def _extract_date(val: Any) -> Optional[datetime.date]:
    if val is None or pd.isna(val):
        return None
    if isinstance(val, datetime.date) and not isinstance(val, datetime.datetime):
        return val
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, (pd.Timestamp, np_datetime := getattr(pd, "Timestamp", None))):
        return val.date()
    try:
        dt = pd.to_datetime(val)
        return dt.date()
    except Exception:
        return None


def closed_daily_signal_frame(
    df: Optional[pd.DataFrame],
    market_date: Optional[datetime.date] = None,
    now: Optional[datetime.datetime] = None,
    ticker: Optional[str] = None,
    as_of: Optional[datetime.datetime] = None,
) -> ClosedFrameResult:
    """Transform an input daily dataframe into a strictly closed-bar frame.
    
    Any bar on or after market_date is excluded.
    Returns ClosedFrameResult with audit fields and the filtered dataframe copy.
    """
    now_dt = as_of or now or datetime.datetime.now(B3_TIMEZONE)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=B3_TIMEZONE)
    else:
        now_dt = now_dt.astimezone(B3_TIMEZONE)

    current_mkt_date = market_date or now_dt.date()
    phase = get_session_phase(now_dt)

    if df is None or df.empty:
        return ClosedFrameResult(
            df=pd.DataFrame() if df is None else df.copy(),
            market_date=current_mkt_date,
            decision_bar_date=None,
            today_bar_removed=False,
            session_phase=phase,
            total_bars_input=0,
            total_bars_output=0,
        )

    clean_df = df.copy()
    input_count = len(clean_df)

    # Determine date column or index
    date_series: Optional[pd.Series] = None
    if "date" in clean_df.columns:
        date_series = clean_df["date"]
    elif "datetime" in clean_df.columns:
        date_series = clean_df["datetime"]
    elif "ts" in clean_df.columns:
        date_series = clean_df["ts"]
    else:
        # Check index
        if isinstance(clean_df.index, pd.DatetimeIndex):
            date_series = pd.Series(clean_df.index.date, index=clean_df.index)
        else:
            try:
                date_series = pd.to_datetime(clean_df.index).date
                date_series = pd.Series(date_series, index=clean_df.index)
            except Exception:
                pass

    if date_series is None:
        # Cannot determine dates -> fail closed by returning empty df
        return ClosedFrameResult(
            df=clean_df.iloc[0:0],
            market_date=current_mkt_date,
            decision_bar_date=None,
            today_bar_removed=False,
            session_phase=phase,
            total_bars_input=input_count,
            total_bars_output=0,
        )

    # Convert to standard datetime.date series
    parsed_dates = [_extract_date(v) for v in date_series]
    
    # Filter: retain ONLY bars where bar_date < current_mkt_date
    mask_closed = [d is not None and d < current_mkt_date for d in parsed_dates]
    today_or_future = [d is not None and d >= current_mkt_date for d in parsed_dates]
    today_bar_removed = any(today_or_future)

    closed_df = clean_df.loc[mask_closed].copy()
    output_count = len(closed_df)

    decision_bar_date: Optional[datetime.date] = None
    if output_count > 0:
        last_parsed = [d for d, m in zip(parsed_dates, mask_closed) if m][-1]
        decision_bar_date = last_parsed

    return ClosedFrameResult(
        df=closed_df,
        market_date=current_mkt_date,
        decision_bar_date=decision_bar_date,
        today_bar_removed=today_bar_removed,
        session_phase=phase,
        total_bars_input=input_count,
        total_bars_output=output_count,
    )
