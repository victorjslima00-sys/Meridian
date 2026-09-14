"""Synthetic fixtures only; these are not market observations."""
from datetime import date
from unittest.mock import Mock

import pandas as pd
import pytest

from trading_bot.data import ingestion


def frame():
    return pd.DataFrame({'Open': [10.], 'High': [11.], 'Low': [9.],
                         'Close': [10.], 'Adj Close': [10.], 'Volume': [20000.]},
                        index=pd.DatetimeIndex(['2025-09-01'], name='Date'))


@pytest.mark.parametrize('column', ['Adj Close', 'Volume'])
def test_missing_field_rejects_entire_dataset(column):
    with pytest.raises(ValueError):
        ingestion._normalize(frame().drop(columns=column), 'TEST')


def test_missing_close_is_not_silently_dropped():
    data = frame()
    data.loc[data.index[0], 'Close'] = float('nan')
    with pytest.raises(ValueError):
        ingestion._normalize(data, 'TEST')


def test_current_quote_cannot_replace_missing_history(monkeypatch):
    response = Mock()
    response.json.return_value = {'results': [{'regularMarketPrice': 10.,
        'regularMarketOpen': 10., 'regularMarketDayHigh': 11.,
        'regularMarketDayLow': 9., 'regularMarketVolume': 20000}]}
    monkeypatch.setattr(ingestion.requests, 'get', lambda *a, **k: response)
    with pytest.raises(ValueError):
        ingestion.fetch_brapi('TEST', 'test-only')


def test_suspect_bar_rejects_instead_of_shortening_history(monkeypatch):
    raw = frame().drop(columns='Adj Close')
    raw['Volume'] = 1.
    monkeypatch.setattr(ingestion.yf, 'download', lambda *a, **k: raw.copy())
    with pytest.raises(ValueError):
        ingestion.fetch_yfinance('TEST', date(2025, 9, 1))


def test_valid_normalization_preserves_input():
    raw = frame()
    before = raw.copy(deep=True)
    result = ingestion._normalize(raw, 'TEST')
    pd.testing.assert_frame_equal(raw, before)
    assert len(result) == 1 and result.iloc[0]['adj_close'] == 10.
