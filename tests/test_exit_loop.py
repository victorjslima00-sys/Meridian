"""
P3-A Etapa 2 — split de laços (latência de stop-loss).
=========================================================
Sub-etapa 2a: _run_exit_scan() e _price_is_trustworthy(), isoladas — ainda
não ligadas a nenhum loop em produção (isso é 2b).

_run_exit_scan() varre SÓ tickers com status='active' (custo independe do
tamanho do universo, ao contrário do laço lento que varre todo mundo a
cada ciclo — ver BACKLOG.md). _price_is_trustworthy() é o gate FAIL-CLOSED:
preço não confiável nunca decide nada sobre a posição, só mantém como está.
"""
import math
import os
import sqlite3
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backend.app.data import database as database_module


def _make_price_row(close, open_=None, high=None, low=None):
    """DataFrame de 1 linha, no formato retornado por fetch_recent_data
    (colunas minúsculas: open/high/low/close/volume/date)."""
    if open_ is None:
        open_ = close
    if high is None:
        high = close
    if low is None:
        low = close
    return pd.DataFrame({
        "open": [open_], "high": [high], "low": [low], "close": [close],
        "volume": [1000], "date": [datetime.now()],
    })


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    original_path = database_module.DB_PATH
    database_module.DB_PATH = path
    try:
        database_module.init_db()
    finally:
        database_module.DB_PATH = original_path
    yield path
    os.unlink(path)


def _insert_active_trade(path, ticker, side, entry_price, target_price, stop_loss):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, target_price, "
        "stop_loss, entry_date, ai_rationale, status) VALUES (?,?,?,?,?,?,?,?,?)",
        (ticker, side, 1.0, entry_price, target_price, stop_loss,
         datetime.now(), "t", "active"),
    )
    conn.commit()
    trade_id = conn.execute("SELECT MAX(id) FROM trades").fetchone()[0]
    conn.close()
    return trade_id


def _insert_closed_trade(path, ticker):
    """Histórico de ticker já fechado — simula 'universo grande' sem
    posição ativa alguma; não deve ser tocado pelo exit scan."""
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, exit_price, "
        "target_price, stop_loss, entry_date, exit_date, ai_rationale, status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (ticker, "BUY", 1.0, 10.0, 11.0, 12.0, 9.0,
         datetime.now(), datetime.now(), "t", "closed"),
    )
    conn.commit()
    conn.close()


def _trade_status(path, trade_id):
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT status FROM trades WHERE id = ?", (trade_id,)).fetchone()
    conn.close()
    return row[0] if row else None


class TestPriceIsTrustworthy:
    """Unitários, sem DB — só a lógica de gate fail-closed."""

    def test_preco_valido_e_confiavel(self):
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy(35.50) is True

    def test_none_nao_e_confiavel(self):
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy(None) is False

    def test_zero_nao_e_confiavel(self):
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy(0.0) is False

    def test_negativo_nao_e_confiavel(self):
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy(-5.0) is False

    def test_nan_nao_e_confiavel(self):
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy(math.nan) is False

    def test_string_nao_numerica_nao_e_confiavel(self):
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy("indisponivel") is False

    def test_ohlc_zerado_nao_e_confiavel_mesmo_com_close_valido(self):
        """Artefato conhecido do yfinance: candle do dia corrente com
        Open/High/Low zerados (ver patch cosmético em get_candles) — mesmo
        que o close pareça válido, o candle é dado incompleto."""
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy(35.50, open_=0.0, high=0.0, low=0.0) is False

    def test_ohlc_valido_e_confiavel(self):
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy(35.50, open_=35.0, high=36.0, low=34.5) is True


class TestRunExitScan:
    async def test_exit_scan_touches_only_active_tickers_and_reacts_immediately(
        self, temp_db_path
    ):
        """Universo grande (50 tickers com histórico fechado) + 1 posição
        ativa no stop. O scan deve tocar SÓ o ticker ativo (custo não
        escala com o universo) e fechar a posição numa única passada —
        não precisa esperar um 'ciclo completo' como o laço lento."""
        for i in range(50):
            _insert_closed_trade(temp_db_path, f"TICKER{i}.SA")

        trade_id = _insert_active_trade(
            temp_db_path, "PETR4.SA", "BUY",
            entry_price=30.0, target_price=40.0, stop_loss=28.0,
        )

        df = _make_price_row(close=27.5)  # abaixo do stop_loss=28.0

        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            with patch(
                "backend.app.data.feed.fetch_recent_data",
            ) as mock_fetch, \
                 patch("backend.app.main.ExecutorAgent") as MockExecutor:
                mock_fetch.return_value = df
                mock_executor_instance = MockExecutor.return_value
                mock_executor_instance.close_order.return_value = {
                    "status": "closed", "pnl_pct": -8.3
                }

                from backend.app.main import _run_exit_scan
                await _run_exit_scan()
        finally:
            database_module.DB_PATH = original_path

        # Só o ticker ativo foi consultado, nunca os 50 do "universo".
        assert mock_fetch.call_count == 1
        called_ticker = mock_fetch.call_args[0][0]
        assert called_ticker == "PETR4.SA"

        # Fechado numa única passada do scan (stop batido).
        mock_executor_instance.close_order.assert_called_once()
        args = mock_executor_instance.close_order.call_args[0]
        assert args[0] == trade_id
        assert args[1] == 27.5

    async def test_exit_scan_ignores_tickers_without_active_position(
        self, temp_db_path
    ):
        _insert_closed_trade(temp_db_path, "VALE3.SA")

        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            with patch(
                "backend.app.data.feed.fetch_recent_data",
            ) as mock_fetch:
                from backend.app.main import _run_exit_scan
                await _run_exit_scan()
        finally:
            database_module.DB_PATH = original_path

        mock_fetch.assert_not_called()


class TestExitScanFailClosed:
    @pytest.mark.parametrize("bad_price", [None, 0.0, math.nan])
    async def test_nao_fecha_posicao_com_preco_nao_confiavel(
        self, temp_db_path, bad_price
    ):
        """Posição no stop, mas o feed devolve preço lixo: a posição deve
        permanecer ativa (fail-closed = não agir, nunca 'vender por
        precaução'), close_order nunca é chamado, e um alerta é disparado."""
        trade_id = _insert_active_trade(
            temp_db_path, "ITUB4.SA", "BUY",
            entry_price=30.0, target_price=40.0, stop_loss=28.0,
        )

        df = _make_price_row(close=bad_price)

        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            with patch(
                "backend.app.data.feed.fetch_recent_data",
            ) as mock_fetch, \
                 patch("backend.app.main.ExecutorAgent") as MockExecutor, \
                 patch("backend.app.main._alerta_telegram") as mock_alerta:
                mock_fetch.return_value = df

                from backend.app.main import _run_exit_scan
                await _run_exit_scan()
        finally:
            database_module.DB_PATH = original_path

        MockExecutor.return_value.close_order.assert_not_called()
        assert _trade_status(temp_db_path, trade_id) == "active"
        assert mock_alerta.called

    async def test_ohlc_zerado_tambem_nao_fecha(self, temp_db_path):
        trade_id = _insert_active_trade(
            temp_db_path, "BBDC4.SA", "BUY",
            entry_price=30.0, target_price=40.0, stop_loss=28.0,
        )
        # close "parece" válido, mas open/high/low zerados = candle incompleto
        df = _make_price_row(close=27.0, open_=0.0, high=0.0, low=0.0)

        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            with patch(
                "backend.app.data.feed.fetch_recent_data",
            ) as mock_fetch, \
                 patch("backend.app.main.ExecutorAgent") as MockExecutor, \
                 patch("backend.app.main._alerta_telegram"):
                mock_fetch.return_value = df

                from backend.app.main import _run_exit_scan
                await _run_exit_scan()
        finally:
            database_module.DB_PATH = original_path

        MockExecutor.return_value.close_order.assert_not_called()
        assert _trade_status(temp_db_path, trade_id) == "active"
