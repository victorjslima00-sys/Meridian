"""Contrato de leitura demo; nenhuma conexão com terminal/corretora nos testes."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from trading_bot.broker.mt5_diagnostics import diagnose_demo, main


def account(**changes):
    fields = dict(login=123456, server="Example-Demo", trade_mode=0,
                  currency="USD", name="PRIVATE_ACCOUNT_NAME")
    fields.update(changes)
    return SimpleNamespace(**fields)


def symbol(**changes):
    fields = dict(name="EURUSD", currency_base="EUR", currency_profit="USD",
                  volume_min=0.01, volume_max=100.0, volume_step=0.01,
                  trade_contract_size=100000.0)
    fields.update(changes)
    return SimpleNamespace(**fields)


@pytest.fixture
def api():
    # API restrita: qualquer tentativa de negociar, login ou symbol_select
    # falha por ausência do método, inclusive em caminhos de erro.
    mock = Mock(spec_set=["initialize", "shutdown", "terminal_info",
                         "account_info", "symbols_get"])
    mock.initialize.return_value = True
    mock.terminal_info.return_value = SimpleNamespace(connected=True, build=6180)
    mock.account_info.return_value = account()
    mock.symbols_get.return_value = (symbol(),)
    return mock


def run(api):
    return diagnose_demo(api, terminal_path="C:/MT5/terminal64.exe",
                         expected_server="Example-Demo")


def test_demo_read_only_report_has_no_account_identity(api):
    result = run(api)
    assert result["ok"] is True
    assert result["account_type"] == "demo"
    assert result["read_only"] is True
    assert result["order_execution_tested"] is False
    assert result["currency"] == "USD"
    assert result["symbols"][0]["trade_contract_size"] == 100000
    output = json.dumps(result)
    assert "PRIVATE_ACCOUNT_NAME" not in output
    assert "123456" not in output
    assert "C:/MT5" not in output
    assert "login" not in output
    api.initialize.assert_called_once_with("C:/MT5/terminal64.exe", timeout=10000)
    api.shutdown.assert_called_once_with()


@pytest.mark.parametrize("mode,server,expected_code", [
    (0, "Example-Demo", None),
    (2, "Example-Demo", "not_demo"),
    (0, "Other-Demo", "server_mismatch"),
    (False, "Example-Demo", "invalid_data"),
])
def test_sdk_tuple_records_keep_validation_and_privacy(api, mode, server, expected_code):
    # O SDK retorna tuplas com atributos; Pydantic não as trata como objetos
    # from_attributes. Reproduz o formato observado na conexão Windows.
    def sdk_record(record):
        fields = vars(record)
        record_type = type("SdkRecord", (tuple,), {"__module__": "builtins", **{
            name: property(lambda self, index=index: self[index])
            for index, name in enumerate(fields)
        }})
        return record_type(fields.values())

    api.terminal_info.return_value = sdk_record(SimpleNamespace(connected=True, build=6191))
    api.account_info.return_value = sdk_record(account(trade_mode=mode, server=server))
    api.symbols_get.return_value = (sdk_record(symbol()),)
    result = run(api)
    if expected_code:
        assert result["code"] == expected_code
        api.symbols_get.assert_not_called()
    else:
        assert result["ok"] is True
        assert result["symbols"][0]["name"] == "EURUSD"
        assert result["order_execution_tested"] is False
    assert "PRIVATE_ACCOUNT_NAME" not in json.dumps(result)
    assert "123456" not in json.dumps(result)
    api.shutdown.assert_called_once_with()


@pytest.mark.parametrize("mode", [1, 2, 3, None, False, True, "0", 0.0])
def test_rejects_every_unconfirmed_demo_mode_before_symbols(api, mode):
    api.account_info.return_value = account(trade_mode=mode)
    result = run(api)
    assert result["ok"] is False
    assert "symbols" not in result
    api.symbols_get.assert_not_called()
    api.shutdown.assert_called_once_with()


def test_name_containing_demo_does_not_authorize_real_account(api):
    api.account_info.return_value = account(trade_mode=2)
    assert run(api)["code"] == "not_demo"


def test_unknown_server_rejected_even_for_demo(api):
    api.account_info.return_value = account(server="Different-Demo")
    assert run(api)["code"] == "server_mismatch"
    api.symbols_get.assert_not_called()


@pytest.mark.parametrize("replacement", [account(trade_mode=2), account(login=789), None])
def test_account_change_discards_collected_symbols(api, replacement):
    api.account_info.side_effect = [account(), replacement]
    result = run(api)
    assert result["ok"] is False
    assert "symbols" not in result
    assert "currency" not in result
    api.shutdown.assert_called_once_with()


def test_disconnect_after_read_discards_report(api):
    api.terminal_info.side_effect = [
        SimpleNamespace(connected=True, build=6180),
        SimpleNamespace(connected=False, build=6180),
    ]
    result = run(api)
    assert result["code"] == "terminal_disconnected"
    assert "symbols" not in result


@pytest.mark.parametrize("payload", [None, (), [], (SimpleNamespace(name="BAD"),)])
def test_missing_or_incomplete_instrument_data_fails(api, payload):
    api.symbols_get.return_value = payload
    assert run(api)["ok"] is False


@pytest.mark.parametrize("changes", [
    {"volume_min": float("nan")}, {"volume_max": float("inf")},
    {"volume_step": 0}, {"trade_contract_size": -1},
    {"volume_min": 10, "volume_max": 1}, {"name": ""},
])
def test_invalid_instrument_rules_fail_closed(api, changes):
    api.symbols_get.return_value = (symbol(**changes),)
    result = run(api)
    assert result["ok"] is False
    assert "symbols" not in result


@pytest.mark.parametrize("method", ["initialize", "terminal_info", "account_info", "symbols_get"])
def test_native_errors_are_sanitized_and_connection_is_closed(api, method, capsys, caplog):
    getattr(api, method).side_effect = RuntimeError("SECRET_PASSWORD PRIVATE_ACCOUNT_NAME")
    result = run(api)
    assert result["ok"] is False
    out = capsys.readouterr()
    assert "SECRET_PASSWORD" not in json.dumps(result) + out.out + out.err + caplog.text
    api.shutdown.assert_called_once_with()


def test_failed_initialize_is_failure_not_empty_success(api):
    api.initialize.return_value = False
    assert run(api)["code"] == "connection_failed"
    api.account_info.assert_not_called()
    api.shutdown.assert_called_once_with()


def test_shutdown_failure_is_sanitized(api):
    api.shutdown.side_effect = RuntimeError("PRIVATE_PATH")
    result = run(api)
    assert result["code"] == "disconnect_failed"
    assert "PRIVATE_PATH" not in json.dumps(result)


def test_cli_missing_sdk_is_actionable_and_does_not_import_backend(monkeypatch, tmp_path, capsys):
    from trading_bot.broker import mt5_diagnostics
    terminal = tmp_path / "terminal64.exe"
    terminal.touch()
    monkeypatch.setattr(mt5_diagnostics, "load_sdk", Mock(side_effect=ImportError("SECRET_PATH")))
    code = main(["--terminal", str(terminal), "--server", "Example-Demo"])
    assert code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["code"] == "sdk_unavailable"
    assert "SECRET_PATH" not in json.dumps(result)


def test_cli_rejects_nonexistent_terminal_before_loading_sdk(monkeypatch, tmp_path, capsys):
    from trading_bot.broker import mt5_diagnostics
    loader = Mock()
    monkeypatch.setattr(mt5_diagnostics, "load_sdk", loader)
    code = main(["--terminal", str(tmp_path / "missing.exe"), "--server", "Example-Demo"])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["code"] == "invalid_terminal"
    loader.assert_not_called()
