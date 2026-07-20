"""
honest-dashboard Bloco 2: /api/positions devolve PnL em R$, capital
alocado e preço atual JA CALCULADOS pelo backend. Antes, o frontend
recalculava tudo isso sozinho a partir de entry_price/shares/pnl_pct —
contra a regra do CLAUDE.md ("no frontend, tudo que parece dado É dado
vindo da API, ou não existe"). O banco/schema real é usado (não mock),
mesmo padrão de tests/test_exit_loop.py.
"""
import datetime
import os
import sqlite3
import tempfile

import pytest

from backend.app.data import database as database_module


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


def _insert_trade(path, **overrides):
    defaults = dict(
        ticker="PETR4.SA", side="BUY", shares=10.0, entry_price=30.0,
        exit_price=None, target_price=40.0, stop_loss=28.0,
        entry_date=datetime.datetime.now(), exit_date=None,
        pnl_pct=0.0, exit_reason=None, ai_rationale="teste", status="active",
    )
    defaults.update(overrides)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, exit_price, "
        "target_price, stop_loss, entry_date, exit_date, pnl_pct, exit_reason, "
        "ai_rationale, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            defaults["ticker"], defaults["side"], defaults["shares"],
            defaults["entry_price"], defaults["exit_price"], defaults["target_price"],
            defaults["stop_loss"], defaults["entry_date"], defaults["exit_date"],
            defaults["pnl_pct"], defaults["exit_reason"], defaults["ai_rationale"],
            defaults["status"],
        ),
    )
    conn.commit()
    conn.close()


def _get_positions(temp_db_path):
    from backend.app import main

    original_path = database_module.DB_PATH
    database_module.DB_PATH = temp_db_path
    try:
        return main.get_positions_route()
    finally:
        database_module.DB_PATH = original_path


class TestPosicaoAtivaTrazCalculosProntos:
    def test_alocado_current_price_e_pnl_monetario_para_buy(self, temp_db_path):
        _insert_trade(
            temp_db_path, ticker="PETR4.SA", side="BUY", shares=10.0,
            entry_price=30.0, pnl_pct=10.0, status="active",
        )

        resp = _get_positions(temp_db_path)

        pos = resp["active_positions"][0]
        assert pos["alocado"] == pytest.approx(300.0)
        assert pos["current_price"] == pytest.approx(33.0)
        assert pos["pnl_monetario"] == pytest.approx(30.0)

    def test_current_price_deriva_na_direcao_certa_para_sell(self, temp_db_path):
        _insert_trade(
            temp_db_path, ticker="VALE3.SA", side="SELL", shares=5.0,
            entry_price=60.0, pnl_pct=5.0, status="active",
        )

        resp = _get_positions(temp_db_path)

        pos = resp["active_positions"][0]
        # SELL com PnL positivo = preço caiu em relação à entrada.
        assert pos["current_price"] == pytest.approx(57.0)
        assert pos["pnl_monetario"] == pytest.approx(15.0)


class TestPosicaoFechadaTrazExitReasonECalculos:
    def test_exit_reason_alocado_pnl_monetario_e_current_price_igual_exit_price(
        self, temp_db_path
    ):
        _insert_trade(
            temp_db_path, ticker="ITUB4.SA", side="BUY", shares=20.0,
            entry_price=25.0, exit_price=27.5, pnl_pct=10.0,
            exit_reason="Take Profit hit at 27.5", status="closed",
            exit_date=datetime.datetime.now(),
        )

        resp = _get_positions(temp_db_path)

        pos = resp["closed_positions"][0]
        assert pos["exit_reason"] == "Take Profit hit at 27.5"
        assert pos["alocado"] == pytest.approx(500.0)
        assert pos["pnl_monetario"] == pytest.approx(50.0)
        assert pos["current_price"] == pytest.approx(27.5)
