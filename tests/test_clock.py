from trading_bot.core.clock import today_b3
from datetime import date

def test_today_b3():
    # Deve retornar a data atual do BR
    d = today_b3()
    assert isinstance(d, date)
