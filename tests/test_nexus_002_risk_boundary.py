"""Adversarial and boundary tests for RiskManager and RiskDecision contract (NEXUS-002)."""
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from pydantic import ValidationError

from backend.app.agents.contracts import RiskDecision, TypedSignal, compute_decision_id
from backend.app.agents.risk_manager import RiskManager


VALID_SHA256 = "0" * 64


from tests.conftest import make_synthetic_approval

SYNTHETIC_AUTHORITY = make_synthetic_approval("PETR4", VALID_SHA256)
IDENTITY = {name: getattr(SYNTHETIC_AUTHORITY, name) for name in (
    "strategy_id", "candidate_id", "intended_use",
)}


@pytest.fixture(autouse=True)
def synthetic_approval(monkeypatch):
    """Only the explicit PETR4 synthetic authority is authorized in these unit tests."""
    def lookup(digest, **kwargs):
        if digest != VALID_SHA256:
            raise ValueError("data_approval_required")
        return SYNTHETIC_AUTHORITY
    monkeypatch.setattr("trading_bot.data.approval.require_dataset_approval_by_digest", lookup)


def test_risk_manager_rejects_malformed_raw_dict():
    rm = RiskManager(saldo_livre=1000.0)
    decision = rm.evaluate_trade({})
    assert isinstance(decision, RiskDecision)
    assert decision.approved is False
    assert decision.signal_id == "invalid"
    assert "Invalid strategy signal" in decision.reason


def test_risk_manager_rejects_hold_signal():
    rm = RiskManager(saldo_livre=1000.0)
    sig = TypedSignal.model_validate({
        "ticker": "PETR4",
        "side": "HOLD",
        "price": 30.0,
        "target_price": 30.0,
        "stop_loss": 30.0,
        "reason": "Hold test",
        "generated_at": datetime.now(timezone.utc),
        "dataset_sha256": VALID_SHA256,
        **IDENTITY,
        "dataset_approved": True,
    })
    decision = rm.evaluate_trade(sig)
    assert isinstance(decision, RiskDecision)
    assert decision.approved is False
    assert decision.signal_id == sig.signal_id
    assert "HOLD" in decision.reason


def test_risk_manager_approves_valid_signal_with_deterministic_decision_id(mock_circuit_breaker):
    rm = RiskManager(saldo_livre=1000.0, reference_equity=1000.0)
    sig = TypedSignal.model_validate({
        "ticker": "PETR4",
        "side": "BUY",
        "price": 30.0,
        "target_price": 33.0,
        "stop_loss": 28.5,
        "reason": "Buy test",
        "generated_at": datetime.now(timezone.utc),
        "dataset_sha256": VALID_SHA256,
        **IDENTITY,
        "dataset_approved": True,
    })
    decision = rm.evaluate_trade(sig)
    assert decision.approved is True
    assert decision.signal_id == sig.signal_id
    assert decision.decision_id.startswith("risk_")
    assert len(decision.decision_id) == 5 + 64
    assert decision.allocated_capital > 0


def test_risk_decision_id_sensitivity():
    now = datetime.now(timezone.utc)
    id1 = compute_decision_id("sig_1", True, "ok", 100.0, 33.0, 28.5, now)
    id2 = compute_decision_id("sig_1", True, "ok", 150.0, 33.0, 28.5, now)  # Changed capital
    id3 = compute_decision_id("sig_2", True, "ok", 100.0, 33.0, 28.5, now)  # Changed signal_id
    assert id1 != id2
    assert id1 != id3


def test_risk_manager_rejects_when_circuit_breaker_active():
    rm = RiskManager(saldo_livre=1000.0)
    sig = TypedSignal.model_validate({
        "ticker": "PETR4",
        "side": "BUY",
        "price": 30.0,
        "target_price": 33.0,
        "stop_loss": 28.5,
        "reason": "Buy test",
        "generated_at": datetime.now(timezone.utc),
        "dataset_sha256": VALID_SHA256,
        **IDENTITY,
        "dataset_approved": True,
    })
    with patch("trading_bot.risk.circuit_breaker.CircuitBreaker.can_trade", return_value=False):
        decision = rm.evaluate_trade(sig)
    assert decision.approved is False
    assert "Circuit Breaker ativado" in decision.reason


def test_risk_manager_rejects_when_max_positions_reached():
    rm = RiskManager(saldo_livre=1000.0)
    sig = TypedSignal.model_validate({
        "ticker": "PETR4",
        "side": "BUY",
        "price": 30.0,
        "target_price": 33.0,
        "stop_loss": 28.5,
        "reason": "Buy test",
        "generated_at": datetime.now(timezone.utc),
        "dataset_sha256": VALID_SHA256,
        **IDENTITY,
        "dataset_approved": True,
    })
    # Default max_positions is typically 3
    open_tickers = ["VALE3", "ITUB4", "B3SA3", "BBAS3"]
    decision = rm.evaluate_trade(sig, open_tickers=open_tickers)
    assert decision.approved is False
    assert "posições atingido" in decision.reason


def test_risk_decision_extra_fields_forbidden():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        RiskDecision.model_validate({
            "signal_id": "sig_" + "0" * 64,
            "approved": True,
            "reason": "Valid",
            "allocated_capital": 50.0,
            "target_price": 33.0,
            "stop_loss": 28.5,
            "decision_timestamp": now,
            "extra_forged": "malicious",
        })
