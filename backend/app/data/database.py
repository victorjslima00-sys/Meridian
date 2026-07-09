import sqlite3
import os
from typing import Dict, Any, List
import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "meridian.db")

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
        entry_price REAL,
        exit_price REAL,
        entry_date TIMESTAMP,
        exit_date TIMESTAMP,
        pnl_pct REAL,
        exit_reason TEXT
    )
    ''')
    
    # Check if portfolio exists, if not initialize mock
    cursor.execute("SELECT * FROM portfolio")
    if not cursor.fetchone():
        cursor.execute('''
        INSERT INTO portfolio (initial_capital, current_capital, invested_capital, updated_at)
        VALUES (10000.0, 10500.0, 1200.0, ?)
        ''', (datetime.datetime.now(),))
        
        # Add a fake trade
        cursor.execute('''
        INSERT INTO trades (ticker, side, entry_price, exit_price, entry_date, exit_date, pnl_pct, exit_reason)
        VALUES ('PETR4', 'BUY', 35.50, 36.80, ?, ?, 3.66, 'take_profit')
        ''', (datetime.datetime.now() - datetime.timedelta(days=2), datetime.datetime.now()))
        
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
