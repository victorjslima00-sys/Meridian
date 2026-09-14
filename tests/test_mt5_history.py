from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from trading_bot.broker.mt5_history import Bar, collect, validate_bars


START = datetime(2025, 1, 1, tzinfo=timezone.utc)
END = datetime(2025, 1, 3, tzinfo=timezone.utc)


def rows():
    return np.array([(int(START.timestamp()), 10., 12., 9., 11., 10, 1, 100)],
                    dtype=[(k, 'f8' if k in ('open', 'high', 'low', 'close') else 'i8')
                           for k in Bar.model_fields])


@pytest.fixture
def api():
    api = Mock(spec_set=['initialize', 'shutdown', 'terminal_info', 'account_info',
                         'copy_rates_range', 'TIMEFRAME_D1'])
    api.initialize.return_value = True
    api.TIMEFRAME_D1 = 16408
    api.terminal_info.return_value = SimpleNamespace(connected=True, build=6191)
    api.account_info.return_value = SimpleNamespace(login=123, trade_mode=0, server='Demo', currency='BRL')
    api.copy_rates_range.return_value = rows()
    return api


def run(api):
    return collect(api, terminal='terminal.exe', server='Demo', symbols=['PETR4F'], start=START, end=END)


def test_native_array_and_report_are_not_backtest_authorization(api):
    result = run(api)
    assert result['ok']
    assert result['datasets']['PETR4F']['count'] == 1
    assert result['ready_for_backtest'] is False
    assert result['adjustment_policy'] == 'unknown'
    assert 'login' not in str(result)
    api.shutdown.assert_called_once()


@pytest.mark.parametrize('field,value', [('close', 20.), ('open', float('nan')), ('real_volume', -1)])
def test_invalid_market_data_discarded(api, field, value):
    data = rows()
    data[field] = value
    api.copy_rates_range.return_value = data
    result = run(api)
    assert not result['ok'] and 'datasets' not in result


def test_duplicate_timestamps_rejected():
    with pytest.raises(ValueError):
        validate_bars(np.concatenate([rows(), rows()]), START, END)


@pytest.mark.parametrize('mode,server', [(2, 'Demo'), (False, 'Demo'), (0, 'Other')])
def test_account_guards_precede_history(api, mode, server):
    api.account_info.return_value = SimpleNamespace(login=123, trade_mode=mode, server=server, currency='BRL')
    assert not run(api)['ok']
    api.copy_rates_range.assert_not_called()


def test_account_change_after_collection_discards_all(api):
    before = api.account_info.return_value
    api.account_info.side_effect = [before, before, SimpleNamespace(login=456, trade_mode=0, server='Demo', currency='BRL')]
    result = run(api)
    assert result['code'] == 'account_changed' and 'datasets' not in result


def test_missing_history_is_not_success(api):
    api.copy_rates_range.return_value = None
    assert not run(api)['ok']


def test_shutdown_failure_discards_data(api):
    api.shutdown.side_effect = RuntimeError('secret')
    result = run(api)
    assert result['code'] == 'disconnect_failed' and 'datasets' not in result
    assert 'secret' not in str(result)


def test_current_day_excluded(api):
    assert not collect(api, terminal='terminal.exe', server='Demo', symbols=['PETR4F'],
                       start=START, end=datetime.now(timezone.utc))['ok']
    api.initialize.assert_not_called()
