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
import os
import sqlite3
import tempfile
import pytest
from backend.app.data import database as database_module
from backend.app.agents.executor import ExecutorAgent

@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix='.db')
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
        conn.execute('UPDATE portfolio SET patrimonio_total=?, saldo_disponivel=?, em_posicoes=?, margem_operavel=? WHERE id = (SELECT id FROM portfolio ORDER BY id DESC LIMIT 1)', (saldo_disponivel, saldo_disponivel, em_posicoes, margem_operavel))
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
        assert pf['margem_operavel'] is None
        assert pf['saldo_operavel'] == pytest.approx(80.0)
        assert pf['saldo_operavel'] == pf['saldo_livre']

    def test_margem_abaixo_do_livre_limita_o_operavel(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0, margem_operavel=50.0)
        pf = _get_portfolio(temp_db_path)
        assert pf['saldo_operavel'] == pytest.approx(30.0)

    def test_margem_ja_estourada_operavel_zero_nunca_negativo(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0, margem_operavel=10.0)
        pf = _get_portfolio(temp_db_path)
        assert pf['saldo_operavel'] == 0.0

    def test_margem_acima_do_livre_nao_amplia_o_operavel(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0, margem_operavel=500.0)
        pf = _get_portfolio(temp_db_path)
        assert pf['saldo_operavel'] == pytest.approx(80.0)

class TestSetMargemOperavel:

    def test_negativa_e_rejeitada(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=0.0)
        res = _set_margem(temp_db_path, -1.0)
        assert res['ok'] is False
        assert _get_portfolio(temp_db_path)['margem_operavel'] is None

    def test_acima_do_saldo_disponivel_e_rejeitada(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=0.0)
        res = _set_margem(temp_db_path, 100.01)
        assert res['ok'] is False
        assert _get_portfolio(temp_db_path)['margem_operavel'] is None

    def test_valida_persiste_e_get_reflete(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=10.0)
        res = _set_margem(temp_db_path, 60.0)
        assert res['ok'] is True
        pf = _get_portfolio(temp_db_path)
        assert pf['margem_operavel'] == pytest.approx(60.0)
        assert pf['saldo_operavel'] == pytest.approx(50.0)

    def test_zero_e_valida_e_congela_novas_entradas(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=0.0)
        res = _set_margem(temp_db_path, 0.0)
        assert res['ok'] is True
        assert _get_portfolio(temp_db_path)['saldo_operavel'] == 0.0

def _ordem_aprovada(allocated):
    from backend.app.agents.contracts import ApprovedExecutionIntent, TypedSignal, RiskDecision
    from datetime import datetime, timezone
    from trading_bot.data.approval import compute_candidate_id
    sig = TypedSignal(
        ticker='PETR4.SA', side='BUY', price=10.0, target_price=12.0, stop_loss=9.0,
        reason='teste', dataset_sha256='0'*64, dataset_approved=True,
        generated_at=datetime.now(timezone.utc),
        strategy_id='donchian_breakout', intended_use='PAPER_TRADING',
        candidate_id=compute_candidate_id(
            ticker='PETR4.SA', strategy_id='donchian_breakout', intended_use='PAPER_TRADING',
            dataset_sha256='0'*64, collected_at_utc='2026-09-16T12:00:00Z',
            dataset_artifact_sha256='0'*64, review_csv_sha256='0'*64,
            source_sha256='0'*64, calendar_sha256='0'*64,
            adjustments_sha256='0'*64, point_in_time_sha256='0'*64,
        ),
    )
    dec = RiskDecision(
        signal_id=sig.signal_id, approved=True, allocated_capital=allocated, target_price=12.0,
        stop_loss=9.0, reason='teste', decision_timestamp=datetime.now(timezone.utc)
    )
    from tests.conftest import make_test_evidenced_quote
    return ApprovedExecutionIntent(
        signal=sig,
        risk_decision=dec,
        execution_quote=make_test_evidenced_quote('PETR4.SA', 10.0),
    )

def _executor_para(path):
    from backend.app.runtime_config import RuntimeConfig
    cfg = RuntimeConfig(
        execution_mode="manual",
        kelly_fraction=0.25,
        max_positions=3,
        max_position_fraction=1.0,
        llm_failure_policy="hold",
    )
    ex = ExecutorAgent(config=cfg)
    ex.db_path = path
    return ex

def _snapshot_banco(path):
    conn = sqlite3.connect(path)
    trades = conn.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
    em_pos = conn.execute('SELECT em_posicoes FROM portfolio ORDER BY id DESC LIMIT 1').fetchone()[0]
    conn.close()
    return (trades, em_pos)

class TestExecutorRespeitaMargemOperavel:
    """O portão de capital de TODA entrada (laço automático e manual
    afunilam em execute_order). RED provado antes de existir qualquer
    controle de UI."""

    def test_alocacao_que_estoura_a_margem_e_rejeitada_sem_nenhum_efeito(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0, margem_operavel=30.0)
        antes = _snapshot_banco(temp_db_path)
        intent = _ordem_aprovada(allocated=15.0)
        res = _executor_para(temp_db_path).execute_order(intent)
        assert res['status'] == 'rejected'
        assert 'margem' in res['reason'].lower()
        assert _snapshot_banco(temp_db_path) == antes

    def test_alocacao_dentro_da_margem_executa(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0, margem_operavel=30.0)
        intent = _ordem_aprovada(allocated=9.0)
        res = _executor_para(temp_db_path).execute_order(intent)
        assert res['status'] == 'executed'
        trades, em_pos = _snapshot_banco(temp_db_path)
        assert trades == 1
        assert em_pos == pytest.approx(29.0)

    def test_sem_margem_definida_comportamento_atual_preservado(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0)
        intent = _ordem_aprovada(allocated=15.0)
        res = _executor_para(temp_db_path).execute_order(intent)
        assert res['status'] == 'executed'

    def test_exatamente_na_margem_e_aceito(self, temp_db_path):
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=20.0, margem_operavel=30.0)
        intent = _ordem_aprovada(allocated=10.0)
        res = _executor_para(temp_db_path).execute_order(intent)
        assert res['status'] == 'executed'