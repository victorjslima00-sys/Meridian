from unittest.mock import patch
from trading_bot.risk.correlation import build_returns_matrix
from trading_bot.risk.circuit_breaker import check_correlation

def test_build_returns_matrix_basic():
    import pandas as pd
    from datetime import date, timedelta
    rows = [{"ticker": "A", "ts": date(2024,1,1)+timedelta(days=i),
             "adj_close": 100.0 + i} for i in range(20)]
    df = pd.DataFrame(rows)
    with patch("trading_bot.risk.correlation.load_ohlcv", return_value=df):
        matrix = build_returns_matrix(["A"], start=date(2024,1,1), end=date(2024,1,20))
    assert "A" in matrix
    assert len(matrix["A"]) > 0

def test_check_correlation_no_open_positions():
    assert check_correlation("PETR4", [], {}) is True

def test_check_correlation_blocks_highly_correlated():
    returns = [float(i) for i in range(20)]
    matrix = {"PETR4": returns, "VALE3": returns}  # correlação 1.0
    result = check_correlation("PETR4", ["VALE3"], matrix, correlation_max=0.7)
    assert result is False

def test_check_correlation_allows_uncorrelated():
    import random
    random.seed(42)
    r1 = [random.gauss(0, 1) for _ in range(30)]
    r2 = [-x for x in r1]  # anti-correlação
    matrix = {"A": r1, "B": r2}
    # anti-correlação (-1.0) não bloqueia (só positiva > 0.7 bloqueia)
    result = check_correlation("A", ["B"], matrix, correlation_max=0.7)
    assert result is True
