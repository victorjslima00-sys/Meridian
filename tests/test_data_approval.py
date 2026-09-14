"""Synthetic test data and approvals, isolated from research artifacts."""
import pandas as pd
import hashlib
import json
import pytest
from trading_bot.data import approval
from trading_bot.signals import engine


def test_unapproved_frame_is_blocked_before_indicators(monkeypatch):
    df = pd.DataFrame({'ts': pd.date_range('2020-01-01', periods=210).date,
                       'o': 10., 'h': 11., 'l': 9., 'c': 10., 'adj_close': 10., 'v': 1000.})
    calls = []
    def sma(*a, **k):
        calls.append(True)
        return pd.Series([10.])
    monkeypatch.setattr(engine, '_sma', sma)
    assert engine.compute_signal(df, 'TEST') is None
    assert calls == []


@pytest.mark.parametrize('change', ['none', 'price', 'ticker', 'slice', 'evidence', 'missing', 'duplicate', 'path'])
def test_exact_approval_and_tampering(tmp_path, monkeypatch, change):
    df = pd.DataFrame({'ts': pd.date_range('2020-01-01', periods=210).date,
                       'o': 10., 'h': 11., 'l': 9., 'c': 10., 'adj_close': 10., 'v': 1000.})
    evidence = tmp_path / 'test-evidence.txt'
    evidence.write_bytes(b'SYNTHETIC TEST EVIDENCE ONLY')
    ref = {'path': evidence.name, 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}
    item = {'dataset_sha256': approval.dataset_digest(df, 'TEST'), 'status': 'approved',
            'reviewed_by': 'unit-test', 'review_notes': 'synthetic fixture',
            **{k: ref.copy() for k in ('source', 'calendar', 'adjustments', 'point_in_time')}}
    registry = tmp_path / 'registry.json'
    monkeypatch.setattr(approval, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(approval, 'REGISTRY', registry)
    entries = [item]
    ticker = 'TEST'
    if change == 'price': df.loc[209, 'adj_close'] = 10.01
    if change == 'ticker': ticker = 'OTHER'
    if change == 'slice': df = df.iloc[:-1]
    if change == 'evidence': evidence.write_bytes(b'CHANGED')
    if change == 'missing': evidence.unlink()
    if change == 'duplicate': entries.append(item)
    if change == 'path': item['source']['path'] = '../outside.txt'
    registry.write_text(json.dumps({'version': 1, 'approvals': entries}), encoding='utf-8')
    calls = []
    def sma(*a, **k):
        calls.append(True)
        return pd.Series([10.])
    monkeypatch.setattr(engine, '_sma', sma)
    if change == 'none':
        approval.require_data_approval(df, ticker)
    else:
        with pytest.raises(ValueError, match='data_approval_required'):
            approval.require_data_approval(df, ticker)
    assert engine.compute_signal(df, ticker) is None
    assert bool(calls) == (change == 'none')
