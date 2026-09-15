"""
Testes de Integração e Idempotência — Sessão Paper Reproduzível (Vulcan)
========================================================================
Validação estrita do fluxo:
Sinal -> RiskManager -> ExecutorAgent -> Journal em Disco -> Reconciliação Contábil.
Garantia de zero chamadas externas, idempotência sob repetição e ausência de ordens duplicadas.
"""
from __future__ import annotations
import datetime
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from trading_bot.execution.paper_session import PaperSessionRunner, PaperSessionJournal

def _init_test_db(db_path: Path, initial_cash: float=1000.0) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute('\n        CREATE TABLE trades (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            ticker TEXT, side TEXT, shares REAL, entry_price REAL,\n            exit_price REAL, target_price REAL, stop_loss REAL,\n            entry_date TIMESTAMP, exit_date TIMESTAMP,\n            pnl_pct REAL, exit_reason TEXT, ai_rationale TEXT, status TEXT, signal_id TEXT)\n    ')
    conn.execute("\n        CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_one_active_per_ticker\n        ON trades (ticker) WHERE status = 'active'\n    ")
    conn.execute('\n        CREATE TABLE portfolio (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            patrimonio_total REAL DEFAULT 0.0,\n            saldo_disponivel REAL DEFAULT 0.0,\n            em_posicoes REAL DEFAULT 0.0,\n            margem_operavel REAL,\n            updated_at TIMESTAMP\n        )\n    ')
    conn.execute('INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, margem_operavel, updated_at) VALUES (?, ?, 0.0, ?, ?)', (initial_cash, initial_cash, initial_cash, datetime.datetime.now()))
    conn.commit()
    conn.close()

@pytest.fixture
def mock_circuit_breaker():
    breaker = MagicMock()
    breaker.can_trade.return_value = True
    with patch('trading_bot.risk.circuit_breaker.CircuitBreaker.from_config', return_value=breaker):
        yield breaker

def test_paper_session_executes_signal_and_reconciles(tmp_path, mock_circuit_breaker):
    db_file = tmp_path / 'paper_test.db'
    storage_dir = tmp_path / 'paper_sessions'
    _init_test_db(db_file, initial_cash=1000.0)
    runner = PaperSessionRunner(session_id='session_test_001', db_path=str(db_file), storage_dir=str(storage_dir))
    signals = [{'ticker': 'PETR4', 'signal': 'BUY', 'current_price': 30.0, 'target_price': 33.0, 'stop_loss': 28.5, 'confidence': 80, 'reason': 'Donchian 20d Breakout', 'dataset_sha256': '0000000000000000000000000000000000000000000000000000000000000000', 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc)}]
    report = runner.run_cycle(signals=signals)
    assert report.orders_executed == 1
    assert report.orders_skipped == 0
    assert report.orders_rejected == 0
    assert report.reconciliation_ok is True
    assert report.discrepancies == []
    assert report.real_broker_calls == 0
    assert report.status == 'RECONCILED'
    conn = sqlite3.connect(db_file)
    trade = conn.execute('SELECT ticker, side, shares, entry_price, status FROM trades').fetchone()
    assert trade is not None
    assert trade[0] == 'PETR4'
    assert trade[1] == 'BUY'
    assert trade[4] == 'active'
    pf = conn.execute('SELECT saldo_disponivel, em_posicoes FROM portfolio ORDER BY id DESC LIMIT 1').fetchone()
    assert pf[0] == 1000.0
    assert pf[1] > 0.0
    saldo_livre = pf[0] - pf[1]
    assert saldo_livre < 1000.0
    assert pytest.approx(saldo_livre + pf[1]) == 1000.0
    conn.close()
    journal_path = storage_dir / 'session_test_001.jsonl'
    assert journal_path.is_file()
    lines = [json.loads(l) for l in journal_path.read_text(encoding='utf-8').splitlines() if l.strip()]
    event_types = [l['event_type'] for l in lines]
    assert 'SESSION_START' in event_types
    assert 'SIGNAL_EVALUATED' in event_types
    assert 'RISK_DECISION' in event_types
    assert 'ORDER_EXECUTED' in event_types
    assert 'RECONCILIATION' in event_types
    assert 'SESSION_END' in event_types
    report_path = storage_dir / 'session_test_001_report.json'
    manifest_path = storage_dir / 'session_test_001_report.manifest.json'
    assert report_path.is_file()
    assert manifest_path.is_file()

def test_paper_session_idempotent_on_replay_no_duplicate_orders(tmp_path, mock_circuit_breaker):
    """Garante que rodar o mesmo sinal novamente NÃO duplica a ordem nem debita caixa."""
    db_file = tmp_path / 'paper_test.db'
    storage_dir = tmp_path / 'paper_sessions'
    _init_test_db(db_file, initial_cash=1000.0)
    signals = [{'ticker': 'PETR4', 'signal': 'BUY', 'current_price': 30.0, 'target_price': 33.0, 'stop_loss': 28.5, 'confidence': 80, 'reason': 'Test Signal', 'dataset_sha256': '0000000000000000000000000000000000000000000000000000000000000000', 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc)}]
    runner1 = PaperSessionRunner(session_id='session_idem_01', db_path=str(db_file), storage_dir=str(storage_dir))
    rep1 = runner1.run_cycle(signals=signals)
    assert rep1.orders_executed == 1
    conn = sqlite3.connect(db_file)
    cash_after_rep1 = conn.execute('SELECT saldo_disponivel, em_posicoes FROM portfolio ORDER BY id DESC LIMIT 1').fetchone()
    count_rep1 = conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'active'").fetchone()[0]
    conn.close()
    assert count_rep1 == 1
    runner2 = PaperSessionRunner(session_id='session_idem_01', db_path=str(db_file), storage_dir=str(storage_dir))
    rep2 = runner2.run_cycle(signals=signals)
    assert rep2.orders_executed == 0
    assert rep2.orders_skipped == 1
    assert rep2.reconciliation_ok is True
    conn = sqlite3.connect(db_file)
    cash_after_rep2 = conn.execute('SELECT saldo_disponivel, em_posicoes FROM portfolio ORDER BY id DESC LIMIT 1').fetchone()
    count_rep2 = conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'active'").fetchone()[0]
    conn.close()
    assert count_rep2 == 1
    assert cash_after_rep1 == cash_after_rep2

def test_paper_session_resumes_interrupted_session(tmp_path, mock_circuit_breaker):
    """Simula interrupção no meio do lote e retomada limpa."""
    db_file = tmp_path / 'paper_test.db'
    storage_dir = tmp_path / 'paper_sessions'
    _init_test_db(db_file, initial_cash=2000.0)
    sig_petr = {'ticker': 'PETR4', 'signal': 'BUY', 'current_price': 30.0, 'target_price': 33.0, 'stop_loss': 28.5, 'confidence': 80, 'reason': 'Sinal 1', 'dataset_sha256': '0000000000000000000000000000000000000000000000000000000000000000', 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc)}
    sig_vale = {'ticker': 'VALE3', 'signal': 'BUY', 'current_price': 60.0, 'target_price': 66.0, 'stop_loss': 57.0, 'confidence': 80, 'reason': 'Sinal 2', 'dataset_sha256': '0000000000000000000000000000000000000000000000000000000000000000', 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc)}
    runner_step1 = PaperSessionRunner(session_id='session_resume_01', db_path=str(db_file), storage_dir=str(storage_dir))
    runner_step1.run_cycle(signals=[sig_petr])
    runner_step2 = PaperSessionRunner(session_id='session_resume_01', db_path=str(db_file), storage_dir=str(storage_dir))
    rep2 = runner_step2.run_cycle(signals=[sig_petr, sig_vale])
    assert rep2.orders_executed == 1
    assert rep2.orders_skipped == 1
    assert rep2.reconciliation_ok is True
    conn = sqlite3.connect(db_file)
    active_tickers = {r[0] for r in conn.execute("SELECT ticker FROM trades WHERE status = 'active'").fetchall()}
    conn.close()
    assert active_tickers == {'PETR4', 'VALE3'}

def test_paper_session_exit_management_and_reconciliation(tmp_path, mock_circuit_breaker):
    """Valida abertura de trade, posterior acionamento de Take Profit e retorno de capital reconciliado."""
    db_file = tmp_path / 'paper_test.db'
    storage_dir = tmp_path / 'paper_sessions'
    _init_test_db(db_file, initial_cash=1000.0)
    runner = PaperSessionRunner(session_id='session_exit_01', db_path=str(db_file), storage_dir=str(storage_dir))
    sig = {'ticker': 'PETR4', 'signal': 'BUY', 'current_price': 30.0, 'target_price': 33.0, 'stop_loss': 28.5, 'confidence': 80, 'reason': 'Entrada', 'dataset_sha256': '0000000000000000000000000000000000000000000000000000000000000000', 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc)}
    rep1 = runner.run_cycle(signals=[sig])
    assert rep1.orders_executed == 1
    runner_exit = PaperSessionRunner(session_id='session_exit_01', db_path=str(db_file), storage_dir=str(storage_dir))
    rep2 = runner_exit.run_cycle(signals=[], current_prices={'PETR4': 34.0})
    assert rep2.orders_closed == 1
    assert rep2.reconciliation_ok is True
    conn = sqlite3.connect(db_file)
    trade = conn.execute("SELECT status, exit_price, pnl_pct FROM trades WHERE ticker = 'PETR4'").fetchone()
    assert trade[0] == 'closed'
    assert trade[1] == 34.0
    assert trade[2] > 0
    pf = conn.execute('SELECT saldo_disponivel, em_posicoes FROM portfolio ORDER BY id DESC LIMIT 1').fetchone()
    assert pf[1] == 0.0
    assert pf[0] > 1000.0
    conn.close()

def test_paper_session_risk_rejection_fail_closed(tmp_path, mock_circuit_breaker):
    """Valida que sinal rejeitado pelo RiskManager não altera o portfólio nem cria trade."""
    db_file = tmp_path / 'paper_test.db'
    storage_dir = tmp_path / 'paper_sessions'
    _init_test_db(db_file, initial_cash=1000.0)
    runner = PaperSessionRunner(session_id='session_risk_rej', db_path=str(db_file), storage_dir=str(storage_dir))
    signals = [{'ticker': 'PETR4', 'signal': 'HOLD', 'current_price': 30.0, 'target_price': 0.0, 'stop_loss': 0.0, 'confidence': 0, 'reason': 'Sem sinal claro', 'dataset_sha256': '0000000000000000000000000000000000000000000000000000000000000000', 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc)}]
    report = runner.run_cycle(signals=signals)
    assert report.orders_executed == 0
    assert report.orders_rejected == 1
    assert report.reconciliation_ok is True
    conn = sqlite3.connect(db_file)
    count = conn.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
    pf = conn.execute('SELECT saldo_disponivel FROM portfolio ORDER BY id DESC LIMIT 1').fetchone()[0]
    conn.close()
    assert count == 0
    assert pf == 1000.0

def test_paper_session_guarantees_zero_real_broker_calls(tmp_path, mock_circuit_breaker):
    """Garante de ponta a ponta que nenhuma requisição de rede para brokers reais é feita."""
    db_file = tmp_path / 'paper_test.db'
    storage_dir = tmp_path / 'paper_sessions'
    _init_test_db(db_file, initial_cash=1000.0)
    signals = [{'ticker': 'PETR4', 'signal': 'BUY', 'current_price': 30.0, 'target_price': 33.0, 'stop_loss': 28.5, 'confidence': 80, 'reason': 'Teste', 'dataset_sha256': '0000000000000000000000000000000000000000000000000000000000000000', 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc)}]
    with patch('urllib.request.urlopen') as mock_url:
        runner = PaperSessionRunner(session_id='session_zero_broker', db_path=str(db_file), storage_dir=str(storage_dir))
        report = runner.run_cycle(signals=signals)
        mock_url.assert_not_called()
        assert report.real_broker_calls == 0