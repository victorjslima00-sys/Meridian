"""Synthetic fixtures test rejection; they are not financial evidence."""
import json

import pytest

from trading_bot.prototype import inspect_collection


def payload():
    return dict(ok=True, read_only=True, order_execution_tested=False,
                source='MetaTrader5 demo', server='XPMT5-DEMO', currency='BRL',
                collected_at_utc='2025-01-04T00:00:00+00:00', timeframe='D1',
                requested_start_utc='2025-01-01T00:00:00+00:00',
                requested_end_utc='2025-01-02T23:59:59+00:00',
                adjustment_policy='unknown', calendar_completeness_verified=False,
                ready_for_backtest=False, datasets={'TEST': dict(
                    bars=[dict(time=1735776000, open=10., high=11., low=9., close=10.,
                               tick_volume=1, spread=1, real_volume=1)], count=1,
                    first_bar_utc='2025-01-02T00:00:00+00:00',
                    last_bar_utc='2025-01-02T00:00:00+00:00', zero_real_volume_count=0)})


def inspect(p):
    return inspect_collection(json.dumps(p).encode())


def test_valid_structure_does_not_authorize_signal_or_fabricate_results():
    r = inspect(payload())
    assert r['structural_validation'] == 'passed'
    assert r['status'] == 'blocked'
    assert r['signal_status'] == 'not_evaluated'
    assert r['performance'] is None
    assert r['order_status'] == 'not_attempted'


@pytest.mark.parametrize('field,value', [('server', 'XPMT5-PRD'), ('ok', False),
                                      ('collected_at_utc', '2099-01-01T00:00:00Z')])
def test_rejects_wrong_identity_and_future(field, value):
    p = payload()
    p[field] = value
    assert inspect(p)['blockers'] == ['invalid_collection']


@pytest.mark.parametrize('fault', ['count', 'duplicate', 'nan', 'range', 'zero_count'])
def test_rejects_inconsistent_data(fault):
    p = payload()
    d = p['datasets']['TEST']
    if fault == 'count': d['count'] = 2
    if fault == 'duplicate': d['bars'] *= 2; d['count'] = 2
    if fault == 'nan': d['bars'][0]['close'] = float('nan')
    if fault == 'range': d['bars'][0]['close'] = 20.
    if fault == 'zero_count': d['zero_real_volume_count'] = 1
    assert inspect(p)['blockers'] == ['invalid_collection']


def test_producer_claims_cannot_unlock():
    p = payload()
    p.update(ready_for_backtest=True, adjustment_policy='approved', calendar_completeness_verified=True)
    assert inspect(p)['status'] == 'blocked'
    assert 'reviewed_signal_dataset_required' in inspect(p)['blockers']


def test_hash_tracks_original_bytes_and_invalid_json_is_blocked():
    a = inspect_collection(b'{}')
    b = inspect_collection(b'{ }')
    assert a['input_sha256'] != b['input_sha256']
    assert inspect_collection(b'not-json')['blockers'] == ['invalid_collection']
