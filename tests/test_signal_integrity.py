"""Synthetic input fixtures: never financial research data."""
import pandas as pd
import pytest
from trading_bot.signals import engine


@pytest.mark.parametrize('defect', ['nan_volume', 'duplicate', 'unordered', 'missing', 'negative', 'range'])
def test_invalid_history_never_reaches_indicators(monkeypatch, defect):
    frame = pd.DataFrame({'ts': pd.date_range('2020-01-01', periods=210).date,
                          'o': 10., 'h': 11., 'l': 9., 'c': 10., 'adj_close': 10., 'v': 1000.})
    if defect == 'nan_volume': frame.loc[209, 'v'] = float('nan')
    if defect == 'duplicate': frame.loc[209, 'ts'] = frame.loc[208, 'ts']
    if defect == 'unordered': frame = frame.iloc[::-1]
    if defect == 'missing': frame = frame.drop(columns='v')
    if defect == 'negative': frame.loc[209, 'adj_close'] = -1.
    if defect == 'range': frame.loc[209, 'l'] = 12.
    called = []
    def indicator(*args, **kwargs):
        called.append(True)
        return pd.Series([10.])
    monkeypatch.setattr(engine, '_sma', indicator)
    try:
        result = engine.compute_signal(frame, 'TEST')
    except (ValueError, KeyError):
        result = None
    assert result is None
    assert not called, 'Unvalidated data reached an indicator'
