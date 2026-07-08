import sqlite3
import datetime
from typing import Optional
from .base import BaseBroker, Order, OrderStatus

class CedroBroker(BaseBroker):
    def __init__(self, db_path: str = "data/trading_bot.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                qty INTEGER NOT NULL,
                price REAL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL
            )
        ''')
        conn.commit()
        conn.close()

    def submit_order(self, ticker: str, side: str, qty: int, price: Optional[float] = None, stop: Optional[float] = None, target: Optional[float] = None) -> Order:
        # Paper trading mode - no real HTTP requests
        # Simulate order submission
        status = OrderStatus.OPEN.value
        created_at = datetime.datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO paper_trades (ticker, side, qty, price, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (ticker, side, qty, price, created_at, status))
        order_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return Order(
            ticker=ticker,
            side=side,
            qty=qty,
            price=price,
            stop=stop,
            target=target,
            status=OrderStatus.OPEN,
            id=order_id
        )

    def cancel_order(self, order_id: int) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE paper_trades
            SET status = ?
            WHERE id = ?
        ''', (OrderStatus.CANCELLED.value, order_id))
        
        rowcount = cursor.rowcount
        conn.commit()
        conn.close()
        return rowcount > 0


# ---------------------------------------------------------------------------
# Alias de compatibilidade
# ---------------------------------------------------------------------------
# O módulo foi criado com o nome CedroBroker, mas código de produção e
# testes e2e importam CedroClient. O alias permite ambos os nomes funcionarem.
CedroClient = CedroBroker
