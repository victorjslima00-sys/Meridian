"""
Testes de integração do CircuitBreaker.can_trade() com equity_snapshots.

Reproduzem o bug: can_trade() passava o mesmo equity como initial_equity,
equity_start_of_day e equity_30d_ago, então drawdowns davam sempre 0% e o
breaker nunca disparava. Também cobrem o comportamento FAIL-CLOSED: sem
snapshots suficientes ou com erro de banco, novas entradas são bloqueadas.

Datas de snapshot usam timezone America/Sao_Paulo (pregão B3).
"""
import datetime
import sqlite3
from zoneinfo import ZoneInfo

import pytest

import backend.app.data.database as database
from trading_bot.risk.circuit_breaker import CircuitBreaker

TZ_SP = ZoneInfo("America/Sao_Paulo")


def _hoje_sp() -> datetime.date:
    return datetime.datetime.now(TZ_SP).date()


def _seed_db(db_path: str, saldo_disponivel: float, snapshots: list[tuple[str, float]]):
    """Cria schema mínimo (portfolio, trades, equity_snapshots) e popula."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                patrimonio_total  REAL DEFAULT 0.0,
                saldo_disponivel  REAL DEFAULT 100.0,
                em_posicoes       REAL DEFAULT 0.0,
                updated_at        TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT, side TEXT, shares REAL,
                entry_price REAL, exit_price REAL,
                target_price REAL, stop_loss REAL,
                entry_date TIMESTAMP, exit_date TIMESTAMP,
                pnl_pct REAL, exit_reason TEXT, ai_rationale TEXT, status TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                date       TEXT PRIMARY KEY,
                equity     REAL NOT NULL,
                created_at TIMESTAMP
            )
            """
        )
        cursor.execute(
            "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, updated_at) VALUES (0.0, ?, 0.0, ?)",
            (saldo_disponivel, datetime.datetime.now(TZ_SP).isoformat()),
        )
        for snap_date, equity in snapshots:
            cursor.execute(
                "INSERT OR REPLACE INTO equity_snapshots (date, equity, created_at) VALUES (?, ?, ?)",
                (snap_date, equity, datetime.datetime.now(TZ_SP).isoformat()),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_trading_bot.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)
    return db_path


def test_can_trade_blocks_on_10pct_drawdown(temp_db):
    """
    Equity atual 90 vs snapshots em 100 = drawdown de 10%, acima do limite
    diário default (5%). O breaker DEVE disparar e bloquear novas entradas.

    No código antigo (stub), initial/start_of_day/30d eram todos iguais ao
    equity atual, drawdown dava 0% e este teste FALHA (can_trade retorna True).
    """
    hoje = _hoje_sp()
    _seed_db(
        temp_db,
        saldo_disponivel=90.0,
        snapshots=[
            ((hoje - datetime.timedelta(days=35)).isoformat(), 100.0),  # initial
            ((hoje - datetime.timedelta(days=30)).isoformat(), 100.0),  # 30d atrás
            (hoje.isoformat(), 100.0),  # início do dia
        ],
    )
    cb = CircuitBreaker()  # defaults: daily 5%, inception 20%, 30d 15%
    assert cb.can_trade() is False


def test_can_trade_fail_closed_sem_snapshots(temp_db):
    """Sem nenhum snapshot na tabela → FAIL-CLOSED: bloquear novas entradas."""
    _seed_db(temp_db, saldo_disponivel=100.0, snapshots=[])
    cb = CircuitBreaker()
    assert cb.can_trade() is False


def test_can_trade_fail_closed_erro_de_banco(tmp_path, monkeypatch):
    """Erro de banco (path inexistente) → FAIL-CLOSED: bloquear novas entradas."""
    monkeypatch.setattr(
        database, "DB_PATH", str(tmp_path / "nao_existe" / "sem_db.db")
    )
    cb = CircuitBreaker()
    assert cb.can_trade() is False


def test_can_trade_permite_com_equity_estavel(temp_db):
    """Equity estável (100 vs snapshots 100) → nenhum gate dispara, pode operar."""
    hoje = _hoje_sp()
    _seed_db(
        temp_db,
        saldo_disponivel=100.0,
        snapshots=[
            ((hoje - datetime.timedelta(days=35)).isoformat(), 100.0),
            ((hoje - datetime.timedelta(days=30)).isoformat(), 100.0),
            (hoje.isoformat(), 100.0),
        ],
    )
    cb = CircuitBreaker()
    assert cb.can_trade() is True
