"""
Usabilidade 2e — margem operável do bot (mexe em capital: rigor máximo,
RED provado antes do controle de UI existir).

Semântica: margem_operavel é um TETO de exposição total do bot dentro do
saldo_disponivel — em_posicoes + novas alocações nunca podem passar dela.
NULL = sem teto (comportamento idêntico ao anterior, backward-compatible
com bancos existentes).

Uma fonte de verdade: get_portfolio() calcula saldo_operavel =
  sem margem  -> saldo_livre
  com margem  -> min(saldo_livre, max(0, margem_operavel - em_posicoes))
e TODO consumidor (sizing do laço automático, rota manual, UI) lê esse
campo — nunca recalcula por conta própria.

Ponto único de enforcement: executor.execute_order — toda entrada, do
laço automático OU manual, afunila ali; se a alocação estourar a margem,
a ordem é rejeitada dentro da mesma transação (nenhum efeito no banco).
"""
import datetime
import os
import sqlite3
import tempfile

import pytest

from backend.app.data import database as database_module
from backend.app.agents.executor import ExecutorAgent


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


def _set_portfolio(path, saldo_disponivel, em_posicoes, margem_operavel=None):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "UPDATE portfolio SET saldo_disponivel=?, em_posicoes=?, margem_operavel=? "
            "WHERE id = (SELECT id FROM portfolio ORDER BY id DESC LIMIT 1)",
            (saldo_disponivel, em_posicoes, margem_operavel),
        )
        conn.commit()
    finally:
        conn.close()


def _get_portfolio(path):
    original = database_module.DB_PATH
    database_module.DB_PATH = path
    try:
        return database_module.get_portfolio()
    finally:
        database_module.DB_PATH = original


def _set_margem(path, valor):
    original = database_module.DB_PATH
    database_module.DB_PATH = path
    try:
        return database_module.set_margem_operavel(valor)
    finally:
        database_module.DB_PATH = original


class TestSaldoOperavelEmGetPortfolio:
    def test_sem_margem_definida_saldo_operavel_e_o_saldo_livre(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0)

        pf = _get_portfolio(temp_db_path)

        assert pf["margem_operavel"] is None
        assert pf["saldo_operavel"] == pytest.approx(80.0)
        assert pf["saldo_operavel"] == pf["saldo_livre"]

    def test_margem_abaixo_do_livre_limita_o_operavel(self, temp_db_path):
        # livre = 100 - 20 = 80, mas o teto de exposição é 50 e já há 20
        # em posições: só 30 podem virar novas entradas.
        _set_portfolio(
            temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0, margem_operavel=50.0
        )

        pf = _get_portfolio(temp_db_path)

        assert pf["saldo_operavel"] == pytest.approx(30.0)

    def test_margem_ja_estourada_operavel_zero_nunca_negativo(self, temp_db_path):
        # Exposição atual (20) já passa do teto (10): nada de novas
        # entradas — e nunca um número negativo vazando pra UI/sizing.
        _set_portfolio(
            temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0, margem_operavel=10.0
        )

        pf = _get_portfolio(temp_db_path)

        assert pf["saldo_operavel"] == 0.0

    def test_margem_acima_do_livre_nao_amplia_o_operavel(self, temp_db_path):
        # Teto maior que o livre não cria dinheiro: operável = livre.
        _set_portfolio(
            temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0, margem_operavel=500.0
        )

        pf = _get_portfolio(temp_db_path)

        assert pf["saldo_operavel"] == pytest.approx(80.0)


class TestSetMargemOperavel:
    def test_negativa_e_rejeitada(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=0.0)

        res = _set_margem(temp_db_path, -1.0)

        assert res["ok"] is False
        assert _get_portfolio(temp_db_path)["margem_operavel"] is None

    def test_acima_do_saldo_disponivel_e_rejeitada(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=0.0)

        res = _set_margem(temp_db_path, 100.01)

        assert res["ok"] is False
        assert _get_portfolio(temp_db_path)["margem_operavel"] is None

    def test_valida_persiste_e_get_reflete(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=10.0)

        res = _set_margem(temp_db_path, 60.0)

        assert res["ok"] is True
        pf = _get_portfolio(temp_db_path)
        assert pf["margem_operavel"] == pytest.approx(60.0)
        assert pf["saldo_operavel"] == pytest.approx(50.0)  # 60 - 10 em posições

    def test_zero_e_valida_e_congela_novas_entradas(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=0.0)

        res = _set_margem(temp_db_path, 0.0)

        assert res["ok"] is True
        assert _get_portfolio(temp_db_path)["saldo_operavel"] == 0.0


def _ordem_aprovada(allocated):
    decision = {
        "approved": True,
        "allocated_capital": allocated,
        "target_price": 12.0,
        "stop_loss": 9.0,
        "reason": "teste",
    }
    analysis = {"signal": "BUY", "last_price": 10.0, "reason": "teste"}
    return decision, analysis


def _executor_para(path):
    ex = ExecutorAgent()
    ex.db_path = path
    return ex


def _snapshot_banco(path):
    conn = sqlite3.connect(path)
    trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    em_pos = conn.execute(
        "SELECT em_posicoes FROM portfolio ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    conn.close()
    return trades, em_pos


class TestExecutorRespeitaMargemOperavel:
    """O portão de capital de TODA entrada (laço automático e manual
    afunilam em execute_order). RED provado antes de existir qualquer
    controle de UI."""

    def test_alocacao_que_estoura_a_margem_e_rejeitada_sem_nenhum_efeito(
        self, temp_db_path
    ):
        # margem 30, já 20 em posições: alocar 15 levaria a exposição a 35.
        _set_portfolio(
            temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0, margem_operavel=30.0
        )
        antes = _snapshot_banco(temp_db_path)
        decision, analysis = _ordem_aprovada(allocated=15.0)

        res = _executor_para(temp_db_path).execute_order("PETR4.SA", decision, analysis)

        assert res["status"] == "rejected"
        assert "margem" in res["reason"].lower()
        # Nenhum efeito no banco: nem trade inserido, nem em_posicoes tocado.
        assert _snapshot_banco(temp_db_path) == antes

    def test_alocacao_dentro_da_margem_executa(self, temp_db_path):
        # margem 30, 20 em posições: alocar 9 leva a 29 — dentro do teto.
        _set_portfolio(
            temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0, margem_operavel=30.0
        )
        decision, analysis = _ordem_aprovada(allocated=9.0)

        res = _executor_para(temp_db_path).execute_order("PETR4.SA", decision, analysis)

        assert res["status"] == "executed"
        trades, em_pos = _snapshot_banco(temp_db_path)
        assert trades == 1
        assert em_pos == pytest.approx(29.0)

    def test_sem_margem_definida_comportamento_atual_preservado(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0)
        decision, analysis = _ordem_aprovada(allocated=15.0)

        res = _executor_para(temp_db_path).execute_order("PETR4.SA", decision, analysis)

        assert res["status"] == "executed"

    def test_exatamente_na_margem_e_aceito(self, temp_db_path):
        # Alocação que leva a exposição EXATAMENTE ao teto (20 + 10 = 30):
        # o teto é inclusivo — rejeitar aqui seria um off-by-one de capital.
        _set_portfolio(
            temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0, margem_operavel=30.0
        )
        decision, analysis = _ordem_aprovada(allocated=10.0)

        res = _executor_para(temp_db_path).execute_order("PETR4.SA", decision, analysis)

        assert res["status"] == "executed"
