import sqlite3
import datetime
from typing import Dict, Any
from ..data.database import DB_PATH

class ExecutorAgent:
    def __init__(self):
        self.db_path = DB_PATH
        
    def execute_order(self, ticker: str, decision: Dict[str, Any], current_price: float):
        """
        Simulates an execution through our 'Paper Trading' broker.
        Writes the trade to the database.
        """
        if not decision.get("approved", False):
            return {"status": "rejected", "reason": "Not approved by risk manager."}
            
        allocated = decision['allocated_capital']
        shares = allocated / current_price
        
        # For simplicity, we just log a theoretical trade entering right now.
        # A real bot would manage open/close states. Here we just mock an entry.
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # We record it as an active trade (exit_price is null)
        cursor.execute('''
        INSERT INTO trades (ticker, side, entry_price, entry_date, exit_reason)
        VALUES (?, 'BUY', ?, ?, 'active')
        ''', (ticker, current_price, datetime.datetime.now()))
        
        # Deduct from portfolio
        cursor.execute("SELECT current_capital, invested_capital FROM portfolio ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            new_current = row[0]
            new_invested = row[1] + allocated
            cursor.execute('''
            UPDATE portfolio SET invested_capital = ?, updated_at = ? WHERE id = (SELECT MAX(id) FROM portfolio)
            ''', (new_invested, datetime.datetime.now()))
            
        conn.commit()
        conn.close()
        
        return {
            "status": "executed",
            "ticker": ticker,
            "shares": shares,
            "price": current_price,
            "total_value": allocated
        }
