"""
Testes de concorrência do ExecutorAgent (P3-A, Etapa 1).
==========================================================
Cobre duas raças reais de dinheiro:
  1. close_order chamado duas vezes para o mesmo trade_id (double-close) —
     sem CAS, ambas as chamadas creditam o portfolio, duplicando o valor.
  2. execute_order chamado duas vezes para o mesmo ticker (duas posições
     ativas simultâneas) — sem guarda + índice único, ambas inserem e
     deduzem capital.

Usa arquivo SQLite real (não :memory:) porque a race exige duas conexões
independentes disputando o mesmo lock de arquivo — cada thread abre a sua,
exatamente como duas execuções concorrentes do worker fariam na prática.

O schema vem do init_db() REAL (backend/app/data/database.py), não de um
CREATE TABLE copiado à mão, para que o índice único parcial criado na
Etapa 1 seja exercitado pelo próprio código de produção.

IMPORTANTE (ver CLAUDE.md): o lock do SQLite se comporta diferente em
Windows e Linux. Estes testes toleram AMBOS os modos de falha possíveis
pré-fix (exceção "database is locked" OU sucesso duplo silencioso) —
o CI (Ubuntu) é o juiz final, não o verde local.
"""
import os
import sqlite3
import tempfile
import threading
from datetime import datetime
from unittest.mock import patch
import pytest
from backend.app.data import database as database_module
from backend.app.agents.executor import ExecutorAgent
from tests.conftest import synthetic_identity_kwargs as _authority, make_synthetic_approval


@pytest.fixture(autouse=True)
def btc_usd_approval(monkeypatch):
    """Synthetic authority for this module's BTC-USD concurrency scope only."""
    authority = make_synthetic_approval("BTC-USD", "2" * 64)
    monkeypatch.setattr(
        "trading_bot.data.approval.require_dataset_approval_by_digest",
        lambda d, *a, **kw: authority if d == "2" * 64 else
        (_ for _ in ()).throw(ValueError("data_approval_required")),
    )
_real_connect = sqlite3.connect

@pytest.fixture
def temp_db_path():
    """Cria um arquivo .db temporário com o schema REAL do init_db()."""
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

def _set_portfolio(db_path, saldo_disponivel, em_posicoes):
    conn = _real_connect(db_path)
    conn.execute('UPDATE portfolio SET patrimonio_total = ?, saldo_disponivel = ?, em_posicoes = ?, updated_at = ? WHERE id = (SELECT id FROM portfolio ORDER BY id DESC LIMIT 1)', (saldo_disponivel, saldo_disponivel, em_posicoes, datetime.now()))
    conn.commit()
    conn.close()

def _get_portfolio(db_path):
    conn = _real_connect(db_path)
    row = conn.execute('SELECT saldo_disponivel, em_posicoes FROM portfolio ORDER BY id DESC LIMIT 1').fetchone()
    conn.close()
    return {'saldo_disponivel': row[0], 'em_posicoes': row[1]}

def _insert_active_trade(db_path, ticker, shares, entry_price):
    conn = _real_connect(db_path)
    conn.execute('INSERT INTO trades (ticker, side, shares, entry_price, target_price, stop_loss, entry_date, ai_rationale, status) VALUES (?,?,?,?,?,?,?,?,?)', (ticker, 'BUY', shares, entry_price, entry_price * 1.1, entry_price * 0.9, datetime.now(), 't', 'active'))
    conn.commit()
    trade_id = conn.execute('SELECT MAX(id) FROM trades').fetchone()[0]
    conn.close()
    return trade_id

class TestCloseOrderConcurrency:
    """CAS em close_order: duas chamadas concorrentes no mesmo trade_id
    não podem creditar o portfolio duas vezes."""

    def test_concurrent_double_close_credits_portfolio_exactly_once(self, temp_db_path):
        trade_id = _insert_active_trade(temp_db_path, 'BTC-USD', shares=1.0, entry_price=50.0)
        _set_portfolio(temp_db_path, saldo_disponivel=100.0, em_posicoes=50.0)
        exit_price = 55.0
        barrier = threading.Barrier(2)
        from tests.conftest import make_test_evidenced_quote
        ev = make_test_evidenced_quote('BTC-USD', exit_price)
        results = [None, None]

        def _worker(idx):
            barrier.wait()
            try:
                results[idx] = ExecutorAgent().close_order(trade_id, exit_price, 'Take Profit hit', evidence=ev)
            except Exception as e:
                results[idx] = e
        import contextvars
        with patch('backend.app.agents.executor.sqlite3.connect', side_effect=lambda p, **kw: _real_connect(temp_db_path, **kw)):
            threads = [threading.Thread(target=contextvars.copy_context().run, args=(_worker, i)) for i in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)
        for r in results:
            assert not isinstance(r, Exception), f'close_order vazou exceção: {r!r}'
        portfolio = _get_portfolio(temp_db_path)
        assert portfolio['saldo_disponivel'] == pytest.approx(105.0), f"Crédito duplicado detectado: saldo_disponivel = {portfolio['saldo_disponivel']} (esperado 105.0 - um único crédito)"
        assert portfolio['em_posicoes'] == pytest.approx(0.0)
        statuses = sorted((r['status'] for r in results))
        assert statuses == ['already_closed', 'closed'], f"Esperado um 'closed' e um 'already_closed', obtido: {statuses}"

class TestExecuteOrderConcurrency:
    """Guarda transacional + índice único em execute_order: duas chamadas
    concorrentes para o mesmo ticker não podem abrir duas posições ativas."""

    def test_concurrent_same_ticker_only_one_position_opens(self, temp_db_path):
        from backend.app.agents.contracts import ApprovedExecutionIntent, TypedSignal, RiskDecision
        from datetime import datetime, timezone

        _set_portfolio(temp_db_path, saldo_disponivel=1000.0, em_posicoes=0.0)
        sig1 = TypedSignal(
            ticker='BTC-USD', side='BUY', price=62000.0, target_price=65000.0, stop_loss=60000.0,
            confidence=70, reason='Test 1', dataset_sha256='2'*64, dataset_approved=True,
            generated_at=datetime.now(timezone.utc),
            **_authority('2' * 64, 'BTC-USD'),
        )
        dec1 = RiskDecision(
            signal_id=sig1.signal_id, approved=True, allocated_capital=100.0, target_price=65000.0,
            stop_loss=60000.0, reason='Test reason 1', decision_timestamp=datetime.now(timezone.utc)
        )
        from tests.conftest import make_test_evidenced_quote
        intent1 = ApprovedExecutionIntent(
            signal=sig1,
            risk_decision=dec1,
            execution_quote=make_test_evidenced_quote("BTC-USD", 62000.0),
        )

        sig2 = TypedSignal(
            ticker='BTC-USD', side='BUY', price=62000.0, target_price=65000.0, stop_loss=60000.0,
            confidence=70, reason='Test 2', dataset_sha256='2'*64, dataset_approved=True,
            generated_at=datetime.now(timezone.utc),
            **_authority('2' * 64, 'BTC-USD'),
        )
        dec2 = RiskDecision(
            signal_id=sig2.signal_id, approved=True, allocated_capital=100.0, target_price=65000.0,
            stop_loss=60000.0, reason='Test reason 2', decision_timestamp=datetime.now(timezone.utc)
        )
        intent2 = ApprovedExecutionIntent(
            signal=sig2,
            risk_decision=dec2,
            execution_quote=make_test_evidenced_quote("BTC-USD", 62000.0),
        )
        intents = [intent1, intent2]

        barrier = threading.Barrier(2)
        results = [None, None]
        import contextvars

        def _worker(idx):
            barrier.wait()
            try:
                results[idx] = ExecutorAgent(db_path=temp_db_path).execute_order(intents[idx])
            except Exception as e:
                results[idx] = e
        with patch('backend.app.data.feed.get_current_price', return_value=62000.0), \
             patch('backend.app.agents.executor.sqlite3.connect', side_effect=lambda p, **kw: _real_connect(temp_db_path, **kw)):
            threads = [threading.Thread(target=contextvars.copy_context().run, args=(_worker, i)) for i in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)
        for r in results:
            assert not isinstance(r, Exception), f'execute_order vazou exceção: {r!r}'
        conn = _real_connect(temp_db_path)
        active_count = conn.execute("SELECT COUNT(*) FROM trades WHERE ticker='BTC-USD' AND status='active'").fetchone()[0]
        conn.close()
        assert active_count == 1, f'Esperado exatamente 1 posição ativa para BTC-USD, encontrado {active_count}'
        portfolio = _get_portfolio(temp_db_path)
        assert portfolio['em_posicoes'] == pytest.approx(100.0), f"Capital deduzido incorretamente: em_posicoes = {portfolio['em_posicoes']} (esperado 100.0 - uma única alocação)"
        statuses = sorted((r['status'] for r in results))
        assert statuses == ['executed', 'skipped_existing_position'], f"Esperado um 'executed' e um 'skipped_existing_position', obtido: {statuses}"

class TestUniqueIndexMutation:
    """Teste 4b (mutação): mesmo com a guarda transacional do Python
    'comentada' (aqui simulado indo direto ao SQL, sem passar pelo
    ExecutorAgent/guarda de aplicação), o índice único parcial sozinho
    barra a segunda posição ativa no mesmo ticker."""

    def test_4b_unique_index_alone_blocks_duplicate_active_ticker(self, temp_db_path):
        conn = _real_connect(temp_db_path)
        try:
            conn.execute('INSERT INTO trades (ticker, side, shares, entry_price, entry_date, status) VALUES (?,?,?,?,?,?)', ('BTC-USD', 'BUY', 1.0, 50000.0, datetime.now(), 'active'))
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute('INSERT INTO trades (ticker, side, shares, entry_price, entry_date, status) VALUES (?,?,?,?,?,?)', ('BTC-USD', 'BUY', 2.0, 51000.0, datetime.now(), 'active'))
                conn.commit()
        finally:
            conn.close()

    def test_unique_index_allows_new_active_trade_after_previous_closed(self, temp_db_path):
        """Confere que o índice é parcial (WHERE status='active'), não
        um UNIQUE(ticker) geral — um ticker pode reabrir posição após fechar."""
        conn = _real_connect(temp_db_path)
        conn.execute('INSERT INTO trades (ticker, side, shares, entry_price, entry_date, status) VALUES (?,?,?,?,?,?)', ('ETH-USD', 'BUY', 1.0, 3000.0, datetime.now(), 'active'))
        conn.commit()
        conn.execute("UPDATE trades SET status='closed' WHERE ticker='ETH-USD'")
        conn.commit()
        conn.execute('INSERT INTO trades (ticker, side, shares, entry_price, entry_date, status) VALUES (?,?,?,?,?,?)', ('ETH-USD', 'BUY', 1.0, 3100.0, datetime.now(), 'active'))
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM trades WHERE ticker='ETH-USD' AND status='active'").fetchone()[0]
        conn.close()
        assert count == 1