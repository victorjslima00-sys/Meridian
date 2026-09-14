"""Synthetic fixtures only; exercise real endpoint body without starting workers."""
import ast
from pathlib import Path

import pandas as pd
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


@pytest.fixture
def endpoint(monkeypatch):
    from backend.app.data import feed
    source = Path('backend/app/main.py').read_text(encoding='utf-8-sig')
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'get_candles')
    fn.decorator_list = []
    namespace = {'__package__': 'backend.app', 'HTTPException': HTTPException}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<candles>', 'exec'), namespace)
    app = FastAPI()
    app.get('/api/candles/{ticker}')(namespace['get_candles'])
    def request(frame):
        monkeypatch.setattr(feed, 'fetch_recent_data', lambda *a, **kw: frame)
        return TestClient(app).get('/api/candles/TESTE3')
    return request


def sample():
    return pd.DataFrame([dict(date='2026-09-10', open=10., high=12., low=9., close=11., volume=25.),
                         dict(date='2026-09-11', open=11., high=13., low=10., close=12., volume=30.)])


@pytest.mark.parametrize('field,value', [('open', 0), ('high', 0), ('low', 0), ('close', 0),
    ('open', None), ('close', float('nan')), ('high', float('inf')), ('low', -1),
    ('high', 8), ('low', 12), ('open', 'bad'), ('volume', -1), ('volume', float('inf')),
    ('date', None), ('date', 'bad'), ('date', 0)])
def test_invalid_row_blocks_entire_series(endpoint, field, value):
    frame = sample()
    frame[field] = frame[field].astype(object)
    frame.loc[1, field] = value
    response = endpoint(frame)
    assert response.status_code == 502
    assert response.json()['detail']['code'] == 'invalid_candle_history'
    assert 'candles' not in response.json()


def test_zero_ohlc_not_replaced_with_close(endpoint):
    frame = sample()
    frame.loc[1, ['open', 'high', 'low']] = 0
    assert endpoint(frame).status_code == 502


@pytest.mark.parametrize('field', ['date', 'open', 'high', 'low', 'close', 'volume'])
def test_missing_field_blocks(endpoint, field):
    assert endpoint(sample().drop(columns=field)).status_code == 502


@pytest.mark.parametrize('frame', [None, pd.DataFrame()])
def test_missing_series_explicit(endpoint, frame):
    response = endpoint(frame)
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'candle_history_unavailable'


def test_valid_values_unchanged(endpoint):
    frame = sample()
    before = frame.copy(deep=True)
    response = endpoint(frame)
    assert response.status_code == 200
    assert response.json()['candles'][0] == dict(time='2026-09-10', open=10., high=12., low=9., close=11., value=25.)
    assert len(response.json()['candles']) == 2
    pd.testing.assert_frame_equal(frame, before)


@pytest.mark.parametrize('kind', ['duplicate_day', 'reverse', 'duplicate_column'])
def test_ambiguous_series_blocks(endpoint, kind):
    frame = sample()
    if kind == 'duplicate_day':
        frame.loc[1, 'date'] = frame.loc[0, 'date']
    elif kind == 'reverse':
        frame = frame.iloc[::-1]
    else:
        frame = pd.concat([frame, frame[['close']]], axis=1)
    assert endpoint(frame).status_code == 502
