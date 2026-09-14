"""Diagnóstico local do MT5: somente leitura e exclusivamente conta demo.

Não implementa Broker, não importa a API web, não inicia workers e não
escreve no ledger de paper trading. Nenhuma função de envio de ordens é usada.
Execute explicitamente: python -m trading_bot.broker.mt5_diagnostics --help
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


Nonempty = Annotated[str, Field(min_length=1, max_length=128)]
PositiveNumber = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class _Record(BaseModel):
    model_config = ConfigDict(strict=True, from_attributes=True)

    @classmethod
    def from_sdk(cls, record):
        # Registros nativos do MT5 são tuplas do módulo builtins que Pydantic
        # rejeita em from_attributes. Extrair apenas os campos necessários;
        # tipos, valores ausentes e invariantes continuam sob validação estrita.
        return cls.model_validate({
            field: getattr(record, field, None) for field in cls.model_fields
        })


class _Account(_Record):
    # Identidade usada apenas em memória para detectar troca de conta.
    login: int = Field(gt=0, exclude=True, repr=False)
    server: Nonempty
    trade_mode: int
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3,12}$")]


class _Terminal(_Record):
    connected: bool
    build: int = Field(gt=0)


class Instrument(_Record):
    """Unidades da corretora: volume é em lotes, não em ações ou reais."""
    name: Nonempty
    currency_base: Annotated[str, Field(max_length=12)]
    currency_profit: Annotated[str, Field(min_length=1, max_length=12)]
    volume_min: PositiveNumber
    volume_max: PositiveNumber
    volume_step: PositiveNumber
    trade_contract_size: PositiveNumber

    @model_validator(mode="after")
    def valid_volume_range(self):
        if self.volume_min > self.volume_max or self.volume_step > self.volume_max:
            raise ValueError("Invalid volume range")
        return self


class _Blocked(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message


def _failure(code: str, message: str) -> dict:
    return {"ok": False, "read_only": True, "order_execution_tested": False,
            "code": code, "message": message}


def _demo_account(api, expected_server: str) -> tuple[_Terminal, _Account]:
    terminal = _Terminal.from_sdk(api.terminal_info())
    if not terminal.connected:
        raise _Blocked("terminal_disconnected", "Terminal desconectado da corretora.")
    account = _Account.from_sdk(api.account_info())
    # ACCOUNT_TRADE_MODE_DEMO = 0. Strict int rejeita False, 0.0 e '0'.
    # Não aceitar nome de servidor contendo 'Demo' como prova do tipo da conta.
    if account.trade_mode != 0:
        raise _Blocked("not_demo", "Conta não confirmada como demonstração; diagnóstico bloqueado.")
    if account.server != expected_server:
        raise _Blocked("server_mismatch", "O servidor conectado difere do servidor informado.")
    return terminal, account


def diagnose_demo(api, *, terminal_path: str, expected_server: str) -> dict:
    """Conecta ao terminal indicado, coleta metadados demo e encerra o IPC.

    Sem login/password: utiliza a sessão já configurada pelo usuário. A API
    nativa pode abrir o terminal caso esteja fechado. Nunca mostra dados brutos
    de conta ou exceção. Checagens antes/depois não são um snapshot atômico;
    por isso este diagnóstico não autoriza nem testa execução de ordens.
    """
    result = _failure("diagnostic_failed", "Não foi possível concluir o diagnóstico.")
    try:
        if not terminal_path or not expected_server or not expected_server.strip():
            raise _Blocked("invalid_configuration", "Informe terminal e servidor demo explicitamente.")
        if api.initialize(terminal_path, timeout=10000) is not True:
            raise _Blocked("connection_failed", "Abra o MetaTrader e conecte sua conta demo.")
        terminal, before = _demo_account(api, expected_server)
        raw_symbols = api.symbols_get()
        if not isinstance(raw_symbols, (tuple, list)) or not raw_symbols:
            raise _Blocked("symbols_unavailable", "A corretora não retornou uma lista válida de ativos.")
        # Valida todos antes de limitar a apresentação; nenhuma regra é inferida
        # pelo nome do ativo ou importada do universo B3.
        instruments = [Instrument.from_sdk(s) for s in raw_symbols]
        _, after = _demo_account(api, expected_server)
        if (before.login, before.server, before.currency) != (after.login, after.server, after.currency):
            raise _Blocked("account_changed", "A conta mudou durante a leitura; dados descartados.")
        result = {
            "ok": True,
            "read_only": True,
            "order_execution_tested": False,
            "account_type": "demo",
            "server": before.server,
            "currency": before.currency,
            "terminal_build": terminal.build,
            "collected_at_utc": datetime.now(timezone.utc).isoformat(),
            "symbol_count": len(instruments),
            "symbols": [s.model_dump() for s in instruments[:20]],
            "message": "Conexão demo verificada. Nenhuma ordem enviada ou execução testada.",
        }
    except _Blocked as exc:
        result = _failure(exc.code, exc.message)
    except ValidationError:
        # ValidationError pode incluir o valor de entrada: não serializá-lo.
        result = _failure("invalid_data", "Dados obrigatórios ausentes ou inválidos; leitura descartada.")
    except Exception:
        # O SDK pode incluir caminhos/identificadores em erros. Não usar
        # last_error(), repr(exc), logging.exception ou traceback no relatório.
        result = _failure("diagnostic_failed", "Falha na comunicação com o MetaTrader; tente novamente.")
    finally:
        try:
            api.shutdown()
        except Exception:
            result = _failure("disconnect_failed", "Não foi possível confirmar o encerramento da conexão local.")
    return result


def load_sdk():
    """Importação opcional: Linux e o backend B3 não precisam do pacote MT5."""
    return importlib.import_module("MetaTrader5")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico MetaTrader 5 DEMO, somente leitura.")
    parser.add_argument("--terminal", required=True, help="Caminho absoluto do terminal64.exe instalado.")
    parser.add_argument("--server", required=True, help="Nome exato do servidor da conta demo conectada.")
    args = parser.parse_args(argv)
    terminal = Path(args.terminal)
    if not terminal.is_absolute() or terminal.suffix.lower() != ".exe" or not terminal.is_file():
        result = _failure("invalid_terminal", "Informe o caminho absoluto de um terminal instalado (.exe).")
    else:
        try:
            api = load_sdk()
        except Exception:
            result = _failure("sdk_unavailable", "Instale requirements-mt5.txt no Python Windows de 64 bits.")
        else:
            result = diagnose_demo(api, terminal_path=str(terminal), expected_server=args.server)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
