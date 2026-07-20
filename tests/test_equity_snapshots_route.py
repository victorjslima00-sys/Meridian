"""
honest-dashboard Bloco 3: /api/equity_snapshots devolve a tabela real
equity_snapshots, sem nenhum cálculo — a curva de patrimônio no frontend
deixa de ser fabricada (replay de trades fechados + Sharpe/Drawdown/Alpha
hardcoded) e passa a plotar exatamente o que o backend já grava todo dia
via save_equity_snapshot. Mesmo padrão de banco real de
tests/test_positions_route.py.
"""
import datetime
import os
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


def _get_equity_snapshots_route(temp_db_path):
    from backend.app import main

    original_path = database_module.DB_PATH
    database_module.DB_PATH = temp_db_path
    try:
        return main.get_equity_snapshots_route()
    finally:
        database_module.DB_PATH = original_path


class TestEquitySnapshotsRoute:
    def test_devolve_snapshots_reais_em_ordem_cronologica(self, temp_db_path):
        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            database_module.save_equity_snapshot(datetime.date(2026, 7, 17), 100.0)
            database_module.save_equity_snapshot(datetime.date(2026, 7, 15), 90.0)
            database_module.save_equity_snapshot(datetime.date(2026, 7, 16), 95.0)
        finally:
            database_module.DB_PATH = original_path

        resp = _get_equity_snapshots_route(temp_db_path)

        assert resp["snapshots"] == [
            {"date": "2026-07-15", "equity": 90.0},
            {"date": "2026-07-16", "equity": 95.0},
            {"date": "2026-07-17", "equity": 100.0},
        ]

    def test_vazio_quando_nao_ha_snapshot_ainda(self, temp_db_path):
        resp = _get_equity_snapshots_route(temp_db_path)
        assert resp["snapshots"] == []

    def test_nao_inventa_nenhum_campo_alem_de_data_e_equity(self, temp_db_path):
        """A tentação de sempre é enriquecer com Sharpe/drawdown/benchmark
        fabricado no meio do caminho -- este endpoint só espelha a
        tabela real, sem cálculo nenhum."""
        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            database_module.save_equity_snapshot(datetime.date(2026, 7, 17), 100.0)
        finally:
            database_module.DB_PATH = original_path

        resp = _get_equity_snapshots_route(temp_db_path)

        assert set(resp["snapshots"][0].keys()) == {"date", "equity"}
