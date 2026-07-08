import pytest
import sqlite3
from trading_bot.broker.cedro import CedroBroker
from trading_bot.broker.base import OrderStatus

@pytest.fixture
def broker(tmp_path):
    db_file = tmp_path / "test_trading_bot.db"
    return CedroBroker(db_path=str(db_file))

def test_init_db(broker):
    conn = sqlite3.connect(broker.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='paper_trades'")
    assert cursor.fetchone() is not None
    conn.close()

def test_submit_order(broker):
    order = broker.submit_order("PETR4", "BUY", 100, 35.50)
    assert order.id is not None
    assert order.ticker == "PETR4"
    assert order.side == "BUY"
    assert order.qty == 100
    assert order.price == 35.50
    assert order.status == OrderStatus.OPEN
    
    # Verify in DB
    conn = sqlite3.connect(broker.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM paper_trades WHERE id=?", (order.id,))
    row = cursor.fetchone()
    assert row is not None
    assert row[1] == "PETR4" # ticker
    assert row[2] == "BUY" # side
    assert row[3] == 100 # qty
    assert row[4] == 35.50 # price
    assert row[6] == "OPEN" # status
    conn.close()

def test_cancel_order(broker):
    order = broker.submit_order("VALE3", "SELL", 200)
    assert broker.cancel_order(order.id) is True
    
    # Verify in DB
    conn = sqlite3.connect(broker.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM paper_trades WHERE id=?", (order.id,))
    row = cursor.fetchone()
    assert row[0] == "CANCELLED"
    conn.close()
