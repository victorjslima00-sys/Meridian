"""Structural validation only: does not certify provenance or completeness."""
from datetime import date, datetime

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SignalBar(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    ts: date | datetime
    o: float = Field(gt=0)
    h: float = Field(gt=0)
    l: float = Field(gt=0)
    c: float = Field(gt=0)
    adj_close: float = Field(gt=0)
    v: float = Field(ge=0)

    @model_validator(mode='after')
    def check_range(self):
        if not self.l <= min(self.o, self.c) <= max(self.o, self.c) <= self.h:
            raise ValueError('inconsistent_ohlc')
        return self


def validate_signal_input(df: pd.DataFrame) -> None:
    """Reject, never fill/drop/sort; callers handle ValueError by blocking."""
    try:
        fields = list(SignalBar.model_fields)
        if df.columns.duplicated().any() or any(k not in df.columns for k in fields):
            raise ValueError('schema')
        if df[fields].isna().any().any():
            raise ValueError('null')
        previous = None
        for record in df[fields].to_dict('records'):
            bar = SignalBar.model_validate(record)
            day = bar.ts.date() if isinstance(bar.ts, datetime) else bar.ts
            if previous is not None and day <= previous:
                raise ValueError('timeline')
            previous = day
    except Exception:
        raise ValueError('invalid_signal_history') from None
