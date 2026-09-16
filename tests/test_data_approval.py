"""Synthetic test data and approvals, isolated from research artifacts."""
import pandas as pd
import json
import pytest
from trading_bot.data import approval, approval_candidate
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
    bundle_dir = tmp_path / 'candidates' / 'test'
    raw_df = pd.DataFrame({
        'date': df['ts'],
        'open': df['o'],
        'high': df['h'],
        'low': df['l'],
        'close': df['c'],
        'volume': df['v'],
    })
    manifest = approval_candidate.build_candidate_bundle(
        ticker='TEST',
        output_dir=bundle_dir,
        project_root=tmp_path,
        df=raw_df,
    )
    registry = tmp_path / 'registry.json'
    registry.write_text(json.dumps({'version': 1, 'approvals': []}), encoding='utf-8')
    approval_candidate.approve_candidate(
        candidate_path=bundle_dir / 'candidate_manifest.json',
        reviewed_by='unit-test',
        review_notes='synthetic fixture',
        confirm_digest=manifest.dataset_sha256,
        confirm_candidate_id=manifest.candidate_id,
        confirmation=approval_candidate.APPROVAL_CONFIRMATION_TOKEN,
        registry_path=registry,
        project_root=tmp_path,
    )

    monkeypatch.setattr(approval, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(approval, 'REGISTRY', registry)

    ticker = 'TEST'
    if change == 'price':
        df.loc[209, 'adj_close'] = 10.01
    if change == 'ticker':
        ticker = 'OTHER'
    if change == 'slice':
        df = df.iloc[:-1]
    if change == 'evidence':
        (bundle_dir / 'source.json').write_bytes(b'CHANGED')
    if change == 'missing':
        (bundle_dir / 'source.json').unlink()
    if change == 'duplicate':
        reg_obj = json.loads(registry.read_text(encoding='utf-8'))
        reg_obj['approvals'].append(reg_obj['approvals'][0])
        registry.write_text(json.dumps(reg_obj), encoding='utf-8')
    if change == 'path':
        reg_obj = json.loads(registry.read_text(encoding='utf-8'))
        reg_obj['approvals'][0]['source']['path'] = '../outside.txt'
        registry.write_text(json.dumps(reg_obj), encoding='utf-8')

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
