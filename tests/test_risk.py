import pytest
from trading_bot.risk.circuit_breaker import CircuitBreaker, CircuitBreakerStatus, check_correlation
from trading_bot.risk.position_sizing import calculate_position_size


# ── Circuit Breaker ──────────────────────────────────────────────────────────

def test_circuit_breaker_pass():
    cb = CircuitBreaker()
    status = cb.check(110.0, 100.0, 105.0, 100.0)
    assert not status.triggered


def test_circuit_breaker_zero_equity():
    cb = CircuitBreaker()
    status = cb.check(0.0, 100.0, 100.0, 100.0)
    assert status.triggered
    assert "Falência" in status.reason


def test_circuit_breaker_daily_loss():
    cb = CircuitBreaker(daily_loss_limit=0.05)
    status = cb.check(94.0, 100.0, 100.0, 100.0)
    assert status.triggered
    assert "Perda diária" in status.reason


def test_circuit_breaker_drawdown_inception():
    cb = CircuitBreaker(drawdown_inception=0.20)
    status = cb.check(79.0, 100.0, 120.0, 120.0)
    assert status.triggered
    assert "Drawdown inception" in status.reason


def test_circuit_breaker_drawdown_30d():
    cb = CircuitBreaker(drawdown_rolling_30d=0.15)
    status = cb.check(84.0, 100.0, 90.0, 100.0)
    assert status.triggered
    assert "Drawdown 30d" in status.reason


def test_circuit_breaker_rejeita_threshold_negativo():
    """Sinal errado inverteria a lógica do check() — deve falhar na construção."""
    with pytest.raises(ValueError, match="daily_loss_limit"):
        CircuitBreaker(daily_loss_limit=-0.03)


def test_circuit_breaker_rejeita_threshold_implausivel():
    with pytest.raises(ValueError, match="drawdown_inception"):
        CircuitBreaker(drawdown_inception=0.9)
    with pytest.raises(ValueError, match="drawdown_rolling_30d"):
        CircuitBreaker(drawdown_rolling_30d=0)


def test_circuit_breaker_from_config_carrega_valores_do_yaml():
    """Config do repo tem valores válidos e positivos — from_config deve aceitar."""
    cb = CircuitBreaker.from_config()
    assert 0 < cb.daily_loss_limit <= 0.5
    assert 0 < cb.drawdown_inception <= 0.5
    assert 0 < cb.drawdown_rolling_30d <= 0.5


def test_circuit_breaker_equity_30d_zero_skips():
    """equity_30d_ago=0 nao deve causar divisao por zero."""
    cb = CircuitBreaker(daily_loss_limit=0.05, drawdown_inception=0.20)
    # equity=98: daily_loss=-2% (abaixo de 5%), inception=-2% (abaixo de 20%)
    # equity_30d_ago=0 -> deve pular o check de 30d sem erro
    status = cb.check(98.0, 100.0, 100.0, 0.0)
    assert not status.triggered


# ── Correlation ──────────────────────────────────────────────────────────────

def test_correlation_pass_empty():
    assert check_correlation("PETR4", [], {}, 0.7)


def test_correlation_no_history():
    returns_matrix = {"A": [0.01] * 5}  # < 10 barras
    assert check_correlation("A", ["B"], returns_matrix, 0.7)


def test_correlation_high_blocks():
    returns_matrix = {
        "A": [0.01, 0.02, -0.01, -0.02, 0.01, 0.03, -0.01, 0.02, 0.01, 0.01],
        "B": [0.011, 0.019, -0.009, -0.021, 0.01, 0.032, -0.01, 0.021, 0.009, 0.01]
    }
    assert not check_correlation("A", ["B"], returns_matrix, 0.7)


def test_correlation_low_passes():
    returns_matrix = {
        "A": [0.01, 0.02, -0.01, -0.02, 0.01, 0.03, -0.01, 0.02, 0.01, 0.01],
        "C": [-0.01, -0.02, 0.01, 0.02, -0.01, -0.03, 0.01, -0.02, -0.01, -0.01]
    }
    assert check_correlation("A", ["C"], returns_matrix, 0.7)


# ── Position Sizing ──────────────────────────────────────────────────────────

def test_position_sizing_basic():
    size = calculate_position_size(1000.0, 0.0, 0.25, 3, 0)
    assert size == pytest.approx(250.0)


def test_position_sizing_max_positions_reached():
    size = calculate_position_size(1000.0, 2000.0, 0.25, 3, 3)
    assert size == 0.0


def test_position_sizing_no_cash():
    size = calculate_position_size(0.0, 2000.0, 0.25, 3, 1)
    assert size == 0.0


def test_position_sizing_invalid_kelly_uses_fallback():
    """kelly_fraction inválido deve usar fallback 0.25 sem lançar exceção."""
    size_zero = calculate_position_size(1000.0, 0.0, 0.0, 3, 0)
    size_over = calculate_position_size(1000.0, 0.0, 1.5, 3, 0)
    # Ambos devem usar 0.25 como fallback
    assert size_zero == pytest.approx(250.0)
    assert size_over == pytest.approx(250.0)


def test_position_sizing_capped_by_cash():
    """Quando allocation > capital_cash, deve retornar capital_cash."""
    # total_equity=500, kelly=0.9 → allocation=450, mas cash=200
    size = calculate_position_size(200.0, 300.0, 0.90, 3, 0)
    assert size == pytest.approx(200.0)
