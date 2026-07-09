import sqlite3
import datetime
from typing import Dict, Any
from ..data.database import DB_PATH

class ExecutorAgent:
    def __init__(self):
        self.db_path = DB_PATH
        
    def execute_order(self, ticker: str, decision: Dict[str, Any], analysis: Dict[str, Any]):
        """
        Simulates an execution through our 'Paper Trading' broker.
        Writes the trade to the database.
        """
        if not decision.get("approved", False):
            return {"status": "rejected", "reason": "Not approved by risk manager."}
            
        current_price = analysis.get('last_price', 0.0)
        allocated = decision.get('allocated_capital', 0.0)
        shares = allocated / current_price if current_price > 0 else 0
        
        target_price = decision.get('target_price', 0.0)
        stop_loss = decision.get('stop_loss', 0.0)
        rationale = analysis.get('reason', 'N/A')
        side = analysis.get('signal', 'BUY')
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO trades (ticker, side, shares, entry_price, target_price, stop_loss, entry_date, ai_rationale, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
        ''', (ticker, side, shares, current_price, target_price, stop_loss, datetime.datetime.now(), rationale))
        
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
        
    def close_order(self, trade_id: int, current_price: float, reason: str):
        """
        Closes an active order.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT ticker, side, shares, entry_price FROM trades WHERE id = ?", (trade_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {"status": "error", "reason": "Trade not found."}
            
        ticker, side, shares, entry_price = row
        
        # Calculate PnL
        if side == "BUY":
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            pnl_pct = ((entry_price - current_price) / entry_price) * 100
            
        gross_value = shares * current_price
        
        # Update trade
        cursor.execute('''
        UPDATE trades 
        SET status = 'closed', exit_price = ?, exit_date = ?, pnl_pct = ?, exit_reason = ?
        WHERE id = ?
        ''', (current_price, datetime.datetime.now(), pnl_pct, reason, trade_id))
        
        # Update portfolio
        cursor.execute("SELECT current_capital, invested_capital FROM portfolio ORDER BY id DESC LIMIT 1")
        pf_row = cursor.fetchone()
        if pf_row:
            current_cap = pf_row[0]
            invested_cap = pf_row[1]
            
            # PnL logic on capital
            original_allocation = shares * entry_price
            pnl_value = gross_value - original_allocation
            
            new_current = current_cap + pnl_value
            new_invested = invested_cap - original_allocation
            
            cursor.execute('''
            UPDATE portfolio SET current_capital = ?, invested_capital = ?, updated_at = ? WHERE id = (SELECT MAX(id) FROM portfolio)
            ''', (new_current, new_invested, datetime.datetime.now()))
            
        conn.commit()
        conn.close()
        
        return {
            "status": "closed",
            "trade_id": trade_id,
            "ticker": ticker,
            "exit_price": current_price,
            "pnl_pct": pnl_pct
        }
