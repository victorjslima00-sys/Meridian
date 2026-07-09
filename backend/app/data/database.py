import sqlite3
import os
from typing import Dict, Any, List
import datetime
from pathlib import Path

# Raiz do projeto = 3 níveis acima de backend/app/data/
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DB_PATH = str(PROJECT_ROOT / "data" / "trading_bot.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Portfolio Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        initial_capital REAL,
        current_capital REAL,
        invested_capital REAL,
        updated_at TIMESTAMP
    )
    ''')
    
    # Trades Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT,
        side TEXT,
        shares REAL,
        entry_price REAL,
        exit_price REAL,
        target_price REAL,
        stop_loss REAL,
        entry_date TIMESTAMP,
        exit_date TIMESTAMP,
        pnl_pct REAL,
        exit_reason TEXT,
        ai_rationale TEXT,
        status TEXT
    )
    ''')
    
    # Check if portfolio exists, if not initialize mock
    cursor.execute("SELECT COUNT(*) FROM portfolio")
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
        INSERT INTO portfolio (initial_capital, current_capital, invested_capital)
        VALUES (100.0, 100.0, 0.0)
        ''')
        
    conn.commit()
    conn.close()

def get_portfolio() -> Dict[str, Any]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM portfolio ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {"initial": 0, "current": 0, "invested": 0}
        
    return dict(row)

def get_trades() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades ORDER BY exit_date DESC")
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(r) for r in rows]
