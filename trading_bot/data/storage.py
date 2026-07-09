"""
Módulo 1 — Storage local (SQLite TimeSeries)
============================================
Schema: (ticker, timestamp, open, high, low, close, volume, adjusted_close)

Cache inteligente: re-usa dados históricos e busca apenas o delta.
"""

import logging
import sqlite3
import json
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
import pandas as pd
import datetime

logger = logging.getLogger(__name__)

class StorageInterface(ABC):
    @abstractmethod
    def save_ohlcv(self, df: pd.DataFrame, source: str = "yfinance") -> int:
        pass

    @abstractmethod
    def load_ohlcv(self, ticker: str, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_last_date(self, ticker: str) -> Optional[date]:
        pass

class SQLiteStorage(StorageInterface):
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
        source       TEXT,
        created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ticker, ts)
    );
    CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_ts ON ohlcv (ticker, ts);
    """
    
    def __init__(self, db_path: str = "data/trading_bot.db"):
        self.db_path = db_path
        sqlite3.register_adapter(datetime.date, lambda d: d.isoformat())
        sqlite3.register_converter("DATE", lambda s: datetime.date.fromisoformat(s.decode('utf-8')))
        self._initialize_db()

    @contextmanager
    def _db_connection(self):
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize_db(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._db_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.executescript(self.CREATE_TABLE_SQL)

    def save_ohlcv(self, df: pd.DataFrame, source: str = "yfinance") -> int:
        if df.empty:
            return 0
        rows = df.assign(source=source)[["ticker", "ts", "o", "h", "l", "c", "v", "adj_close", "source"]].to_dict("records")
        with self._db_connection() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO ohlcv (ticker, ts, o, h, l, c, v, adj_close, source) "
                "VALUES (:ticker, :ts, :o, :h, :l, :c, :v, :adj_close, :source)",
                rows,
            )
            inserted = conn.total_changes
        return inserted

    def load_ohlcv(self, ticker: str, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
        query = "SELECT ticker, ts, o, h, l, c, v, adj_close FROM ohlcv WHERE ticker = ?"
        params: list = [ticker]
        if start:
            query += " AND ts >= ?"
            params.append(str(start))
        if end:
            query += " AND ts <= ?"
            params.append(str(end))
        query += " ORDER BY ts ASC"

        with self._db_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params, parse_dates=["ts"])
        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"]).dt.date
        return df

    def get_last_date(self, ticker: str) -> Optional[date]:
        with self._db_connection() as conn:
            row = conn.execute("SELECT MAX(ts) as last_ts FROM ohlcv WHERE ticker = ?", [ticker]).fetchone()
        if row and row["last_ts"]:
            return date.fromisoformat(row["last_ts"])
        return None

class TiDBStorage(StorageInterface):
    """
    Integração ACID com TiDB/MySQL usando SQLAlchemy.
    """
    def __init__(self, db_url: str):
        from sqlalchemy import create_engine, Column, String, Date, Float, MetaData, Table, text
        from sqlalchemy.dialects.mysql import insert
        
        self.engine = create_engine(db_url, pool_recycle=3600)
        self.metadata = MetaData()
        
        self.ohlcv_table = Table(
            'ohlcv', self.metadata,
            Column('ticker', String(20), primary_key=True),
            Column('ts', Date, primary_key=True),
            Column('o', Float),
            Column('h', Float),
            Column('l', Float),
            Column('c', Float, nullable=False),
            Column('v', Float),
            Column('adj_close', Float, nullable=False),
            Column('source', String(50))
        )
        self.metadata.create_all(self.engine)

    def save_ohlcv(self, df: pd.DataFrame, source: str = "yfinance") -> int:
        if df.empty:
            return 0
            
        from sqlalchemy.dialects.mysql import insert
        rows = df.assign(source=source)[["ticker", "ts", "o", "h", "l", "c", "v", "adj_close", "source"]].to_dict("records")
        
        stmt = insert(self.ohlcv_table).values(rows)
        # INSERT IGNORE behavior in TiDB/MySQL
        on_duplicate = stmt.on_duplicate_key_update(
            o=stmt.inserted.o,
            h=stmt.inserted.h,
            l=stmt.inserted.l,
            c=stmt.inserted.c,
            v=stmt.inserted.v,
            adj_close=stmt.inserted.adj_close
        )
        
        with self.engine.begin() as conn:
            result = conn.execute(on_duplicate)
            return result.rowcount

    def load_ohlcv(self, ticker: str, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
        query = "SELECT ticker, ts, o, h, l, c, v, adj_close FROM ohlcv WHERE ticker = %(ticker)s"
        params = {"ticker": ticker}
        if start:
            query += " AND ts >= %(start)s"
            params["start"] = start
        if end:
            query += " AND ts <= %(end)s"
            params["end"] = end
        query += " ORDER BY ts ASC"

        with self.engine.connect() as conn:
            df = pd.read_sql_query(query, conn, params=params, parse_dates=["ts"])
            
        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"]).dt.date
        return df

    def get_last_date(self, ticker: str) -> Optional[date]:
        from sqlalchemy import text
        with self.engine.connect() as conn:
            result = conn.execute(text("SELECT MAX(ts) FROM ohlcv WHERE ticker = :ticker"), {"ticker": ticker}).scalar()
        if result:
            if isinstance(result, str):
                return date.fromisoformat(result)
            return result
        return None

class RedisCacheL2:
    """
    Camada L2 (Cache Distribuído) para comunicação entre containers.
    """
    def __init__(self, redis_url: str):
        import redis
        self.client = redis.from_url(redis_url, decode_responses=True)
        
    def set_open_positions(self, positions: list):
        self.client.set("meridian:open_positions", json.dumps(positions))
        
    def get_open_positions(self) -> list:
        data = self.client.get("meridian:open_positions")
        return json.loads(data) if data else []


# -------------------------------------------------------------
# Factory e Retrocompatibilidade de Funções Globais
# -------------------------------------------------------------

_default_storage: Optional[StorageInterface] = None

def get_storage() -> StorageInterface:
    global _default_storage
    if _default_storage is None:
        from trading_bot.core.config import AppConfig
        cfg = AppConfig.load()
        engine_type = cfg.get("data", "storage", "engine", default="sqlite")
        
        if engine_type == "tidb":
            url = cfg.get("data", "storage", "tidb_url")
            _default_storage = TiDBStorage(url)
        else:
            db_path = cfg.get("data", "storage", "sqlite_path", default="data/trading_bot.db")
            _default_storage = SQLiteStorage(db_path)
    return _default_storage

def _get_storage_for_kwargs(**kwargs) -> StorageInterface:
    if "db_path" in kwargs and kwargs["db_path"]:
        return SQLiteStorage(kwargs["db_path"])
    return get_storage()

def initialize_db(db_path: str = None) -> None:
    """
    Inicializa a storage. 
    Mantido para compatibilidade com os scripts das Fases e testes que importam explicitamente.
    """
    if db_path:
        SQLiteStorage(db_path)
    else:
        get_storage()

def save_ohlcv(df: pd.DataFrame, source: str = "yfinance", **kwargs) -> int:
    return _get_storage_for_kwargs(**kwargs).save_ohlcv(df, source)

def load_ohlcv(ticker: str, start: Optional[date] = None, end: Optional[date] = None, **kwargs) -> pd.DataFrame:
    return _get_storage_for_kwargs(**kwargs).load_ohlcv(ticker, start, end)

def get_last_date(ticker: str, **kwargs) -> Optional[date]:
    return _get_storage_for_kwargs(**kwargs).get_last_date(ticker)

def get_missing_tickers(tickers: list[str], required_start: date, **kwargs) -> list[str]:
    storage = _get_storage_for_kwargs(**kwargs)
    missing = []
    for ticker in tickers:
        last = storage.get_last_date(ticker)
        if last is None or last < required_start:
            missing.append(ticker)
    return missing

def get_delta_start(ticker: str, **kwargs) -> date:
    last = _get_storage_for_kwargs(**kwargs).get_last_date(ticker)
    if last is None:
        from trading_bot.core.clock import today_b3
        return today_b3() - timedelta(days=365 * 5)
    return last + timedelta(days=1)
