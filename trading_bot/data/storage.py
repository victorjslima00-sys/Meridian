"""
Módulo 1 — Storage local (SQLite TimeSeries)
============================================
Schema: (ticker, timestamp, open, high, low, close, volume, adjusted_close)

Cache inteligente: re-usa dados históricos e busca apenas o delta.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

import datetime
sqlite3.register_adapter(datetime.date, lambda d: d.isoformat())
sqlite3.register_converter("DATE", lambda s: datetime.date.fromisoformat(s.decode('utf-8')))

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "data/trading_bot.db"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ohlcv (
    ticker       TEXT    NOT NULL,
    ts           DATE    NOT NULL,
    o            REAL,
    h            REAL,
    l            REAL,
    c            REAL    NOT NULL,
    v            REAL,
    adj_close    REAL    NOT NULL,
    source       TEXT,               -- 'yfinance' ou 'brapi'
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, ts)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_ts ON ohlcv (ticker, ts);
"""


@contextmanager
def _db_connection(db_path: str):
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Cria o banco e as tabelas se não existirem."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with _db_connection(db_path) as conn:
        conn.executescript(CREATE_TABLE_SQL)
    logger.info("DB inicializado: %s", db_path)


def save_ohlcv(
    df: pd.DataFrame,
    source: str = "yfinance",
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """
    Salva DataFrame no banco. Ignora duplicatas (INSERT OR IGNORE).

    Returns:
        Número de linhas inseridas
    """
    if df.empty:
        return 0

    rows = df.assign(source=source)[
        ["ticker", "ts", "o", "h", "l", "c", "v", "adj_close", "source"]
    ].to_dict("records")

    with _db_connection(db_path) as conn:
        cur = conn.executemany(
            """INSERT OR IGNORE INTO ohlcv
               (ticker, ts, o, h, l, c, v, adj_close, source)
               VALUES (:ticker, :ts, :o, :h, :l, :c, :v, :adj_close, :source)""",
            rows,
        )
        inserted = cur.rowcount

    logger.debug("[%s] %d linhas salvas no DB (source=%s)", df["ticker"].iloc[0], inserted, source)
    return inserted


def load_ohlcv(
    ticker: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    """
    Carrega OHLCV do banco para um ticker e período.

    Returns:
        DataFrame com schema padronizado, ordenado por ts ascending
    """
    query = "SELECT ticker, ts, o, h, l, c, v, adj_close FROM ohlcv WHERE ticker = ?"
    params: list = [ticker]

    if start:
        query += " AND ts >= ?"
        params.append(str(start))
    if end:
        query += " AND ts <= ?"
        params.append(str(end))

    query += " ORDER BY ts ASC"

    with _db_connection(db_path) as conn:
        df = pd.read_sql_query(query, conn, params=params, parse_dates=["ts"])

    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"]).dt.date

    return df


def get_last_date(ticker: str, db_path: str = DEFAULT_DB_PATH) -> Optional[date]:
    """Retorna a data mais recente disponível no banco para o ticker."""
    with _db_connection(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(ts) as last_ts FROM ohlcv WHERE ticker = ?", [ticker]
        ).fetchone()

    if row and row["last_ts"]:
        return date.fromisoformat(row["last_ts"])
    return None


def get_missing_tickers(
    tickers: list[str],
    required_start: date,
    db_path: str = DEFAULT_DB_PATH,
) -> list[str]:
    """
    Retorna tickers que precisam ser (re)buscados porque:
    - Não existem no banco, ou
    - Têm dados mais antigos que required_start
    """
    missing = []
    for ticker in tickers:
        last = get_last_date(ticker, db_path)
        if last is None or last < required_start:
            missing.append(ticker)
    return missing


def get_delta_start(ticker: str, db_path: str = DEFAULT_DB_PATH) -> date:
    """
    Cache inteligente: retorna a data a partir da qual buscar dados novos.
    Se o ticker não existe no banco, retorna uma data padrão (5 anos atrás).
    """
    last = get_last_date(ticker, db_path)
    if last is None:
        from trading_bot.core.clock import today_b3
        return today_b3() - timedelta(days=365 * 5)
    # Busca a partir do dia seguinte ao último dado
    return last + timedelta(days=1)
