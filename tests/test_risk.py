import pytest
from trading_bot.risk.circuit_breaker import CircuitBreaker, CircuitBreakerStatus, check_correlation

def test_circuit_breaker_pass():
    cb = CircuitBreaker()
    status = cb.check(
        current_equity=110.0,
        initial_equity=100.0,
        equity_start_of_day=105.0,
        equity_30d_ago=100.0
    )
    assert not status.triggered

def test_circuit_breaker_daily_loss():
    cb = CircuitBreaker(daily_loss_limit=0.05)
    # Start of day 100, drops to 94 (6% loss)
    status = cb.check(94.0, 100.0, 100.0, 100.0)
    assert status.triggered
    assert "Perda diária" in status.reason

def test_circuit_breaker_drawdown_inception():
    cb = CircuitBreaker(drawdown_inception=0.20)
    # Initial 100, drops to 79 (21% loss)
    status = cb.check(79.0, 100.0, 120.0, 120.0)
    assert status.triggered
    assert "Drawdown inception" in status.reason

def test_circuit_breaker_drawdown_30d():
    cb = CircuitBreaker(drawdown_rolling_30d=0.15)
    # 30d ago 100, drops to 84 (16% loss)
    status = cb.check(84.0, 100.0, 90.0, 100.0)
    assert status.triggered
    assert "Drawdown 30d" in status.reason

def test_correlation_pass_empty():
    assert check_correlation("PETR4", [], {}, 0.7)

def test_correlation_high_blocks():
    # Retornos muito correlacionados
    returns_matrix = {
        "A": [0.01, 0.02, -0.01, -0.02, 0.01, 0.03, -0.01, 0.02, 0.01, 0.01],
        "B": [0.011, 0.019, -0.009, -0.021, 0.01, 0.032, -0.01, 0.021, 0.009, 0.01]
    }
    assert not check_correlation("A", ["B"], returns_matrix, 0.7)

def test_correlation_low_passes():
    # Retornos inversos
    returns_matrix = {
        "A": [0.01, 0.02, -0.01, -0.02, 0.01, 0.03, -0.01, 0.02, 0.01, 0.01],
        "C": [-0.01, -0.02, 0.01, 0.02, -0.01, -0.03, 0.01, -0.02, -0.01, -0.01]
    }
    assert check_correlation("A", ["C"], returns_matrix, 0.7)
