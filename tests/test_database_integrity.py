"""
Testes de integridade defensiva do init_db() (P3-A Etapa 1).
================================================================
Antes de criar o índice único idx_trades_one_active_per_ticker, init_db()
detecta duplicata histórica de posição 'active' por ticker (dado de antes
deste fix existir) e falha o startup com diagnóstico claro — em vez de
deixar o CREATE UNIQUE INDEX estourar um IntegrityError críptico sem dizer
qual ticker nem por quê.
"""
import os
import sqlite3
import tempfile
from datetime import datetime
from unittest.mock import patch

import pytest

from backend.app.data import database as database_module


def _make_legacy_schema_with_duplicates(path, tickers_duplicados):
    """Simula um banco de ANTES da Etapa 1: schema de trades sem o índice
    único, já com duplicata de posição ativa por ticker (dado legado que
    o índice, se criado às cegas, não conseguiria acomodar)."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, side TEXT, shares REAL, entry_price REAL,
            exit_price REAL, target_price REAL, stop_loss REAL,
            entry_date TIMESTAMP, exit_date TIMESTAMP,
            pnl_pct REAL, exit_reason TEXT, ai_rationale TEXT, status TEXT
        )
        """
    )
    for ticker in tickers_duplicados:
        for _ in range(2):
            conn.execute(
                "INSERT INTO trades (ticker, side, shares, entry_price, "
                "entry_date, status) VALUES (?,?,?,?,?,?)",
                (ticker, "BUY", 1.0, 100.0, datetime.now(), "active"),
            )
    conn.commit()
    conn.close()


def _index_exists(path) -> bool:
    conn = sqlite3.connect(path)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name='idx_trades_one_active_per_ticker'"
    ).fetchone()
    conn.close()
    return row is not None


class TestInitDbDuplicateGuard:
    def test_init_db_raises_and_lists_affected_tickers_on_legacy_duplicates(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            _make_legacy_schema_with_duplicates(path, ["BTC-USD", "ETH-USD"])

            original_path = database_module.DB_PATH
            database_module.DB_PATH = path
            try:
                with patch(
                    "backend.app.data.database._alerta_telegram_startup"
                ) as mock_alerta:
                    with pytest.raises(RuntimeError) as exc_info:
                        database_module.init_db()
            finally:
                database_module.DB_PATH = original_path

            # Diagnóstico claro: os dois tickers afetados aparecem na
            # mensagem, não um IntegrityError genérico.
            msg = str(exc_info.value)
            assert "BTC-USD" in msg
            assert "ETH-USD" in msg

            # Alerta Telegram foi disparado (best-effort) com o mesmo contexto.
            mock_alerta.assert_called_once()
            assert "BTC-USD" in mock_alerta.call_args[0][0]

            # O índice NÃO foi criado às cegas — o startup abortou antes.
            assert not _index_exists(path)
        finally:
            os.unlink(path)

    def test_init_db_reason_survives_telegram_failure(self):
        """O envio do alerta é best-effort: se ele próprio falhar (ex.: config
        ausente), o RuntimeError de integridade ainda precisa propagar —
        nunca pode ser mascarado por uma falha secundária de notificação."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            _make_legacy_schema_with_duplicates(path, ["PETR4.SA"])

            original_path = database_module.DB_PATH
            database_module.DB_PATH = path
            try:
                with patch(
                    "backend.app.data.database._alerta_telegram_startup",
                    side_effect=RuntimeError("Telegram indisponível"),
                ):
                    with pytest.raises(RuntimeError) as exc_info:
                        database_module.init_db()
            finally:
                database_module.DB_PATH = original_path

            # A exceção que propaga é a de integridade do banco, não a do
            # Telegram — isso só é verdade se _alerta_telegram_startup for
            # chamado ANTES do raise e o próprio init_db não o proteger; como
            # o teste acima prova que o alerta É chamado, e este aqui prova
            # que uma falha nele não impede o RuntimeError certo de subir,
            # a mensagem real (não "Telegram indisponível") deve aparecer.
            assert "PETR4.SA" in str(exc_info.value)
            assert not _index_exists(path)
        finally:
            os.unlink(path)

    def test_init_db_succeeds_without_duplicates(self):
        """Regressão: banco novo (sem dado nenhum) continua inicializando
        normalmente e cria o índice — a checagem não deve gerar falso
        positivo nem quebrar o caminho feliz."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            original_path = database_module.DB_PATH
            database_module.DB_PATH = path
            try:
                with patch(
                    "backend.app.data.database._alerta_telegram_startup"
                ) as mock_alerta:
                    database_module.init_db()
            finally:
                database_module.DB_PATH = original_path

            mock_alerta.assert_not_called()
            assert _index_exists(path)
        finally:
            os.unlink(path)
