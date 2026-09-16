"""Adversarial and integrity tests for TypedSignal contract (NEXUS-002)."""
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from backend.app.agents.contracts import TypedSignal, compute_signal_id


VALID_SHA256 = "0" * 64


@pytest.fixture(autouse=True)
def synthetic_approval(monkeypatch):
    """Synthetic dataset approval for contract unit tests."""
    from trading_bot.data.approval import Approval, Evidence, compute_candidate_id
    ev = Evidence(path="synthetic.csv", sha256=VALID_SHA256)
    c_id = compute_candidate_id(
        ticker="PETR4",
        strategy_id="donchian_breakout",
        intended_use="PAPER_TRADING",
        dataset_sha256=VALID_SHA256,
        collected_at_utc="2026-09-16T12:00:00Z",
        dataset_artifact_sha256=ev.sha256,
        review_csv_sha256=ev.sha256,
        source_sha256=ev.sha256,
        calendar_sha256=ev.sha256,
        adjustments_sha256=ev.sha256,
        point_in_time_sha256=ev.sha256,
    )
    appr = Approval(
        candidate_id=c_id,
        ticker="PETR4",
        strategy_id="donchian_breakout",
        intended_use="PAPER_TRADING",
        dataset_sha256=VALID_SHA256,
        collected_at_utc="2026-09-16T12:00:00Z",
        dataset_artifact=ev,
        review_csv=ev,
        source=ev,
        calendar=ev,
        adjustments=ev,
        point_in_time=ev,
        reviewed_by="nexus-tester",
        review_notes="synthetic fixture",
        status="approved",
    )
    monkeypatch.setattr(
        "trading_bot.data.approval.require_dataset_approval_by_digest",
        lambda d, *a, **kw: appr if d == VALID_SHA256 else (_ for _ in ()).throw(ValueError("data_approval_required"))
    )


def test_valid_buy_signal_contract():
    now = datetime.now(timezone.utc)
    sig = TypedSignal.model_validate({
        "ticker": "PETR4",
        "side": "BUY",
        "price": 30.0,
        "target_price": 33.0,
        "stop_loss": 28.5,
        "reason": "Breakout",
        "generated_at": now,
        "dataset_sha256": VALID_SHA256,
        "dataset_approved": True,
    })
    assert sig.signal_id.startswith("sig_")
    assert len(sig.signal_id) == 4 + 64
    assert sig.price == 30.0
    assert sig.current_price == 30.0
    assert sig.signal == "BUY"


def test_valid_sell_signal_contract():
    now = datetime.now(timezone.utc)
    sig = TypedSignal.model_validate({
        "ticker": "VALE3",
        "side": "SELL",
        "price": 60.0,
        "target_price": 55.0,
        "stop_loss": 62.0,
        "reason": "Breakdown",
        "generated_at": now,
        "dataset_sha256": VALID_SHA256,
        "dataset_approved": True,
    })
    assert sig.signal_id.startswith("sig_")
    assert sig.side == "SELL"


def test_hold_signal_allowed_in_signal_but_no_direction_inversion():
    now = datetime.now(timezone.utc)
    sig = TypedSignal.model_validate({
        "ticker": "ITUB4",
        "side": "HOLD",
        "price": 30.0,
        "target_price": 30.0,
        "stop_loss": 30.0,
        "reason": "Neutral",
        "generated_at": now,
        "dataset_sha256": VALID_SHA256,
        "dataset_approved": True,
    })
    assert sig.signal_id.startswith("sig_")
    assert sig.side == "HOLD"


def test_caller_supplied_matching_signal_id():
    now = datetime.now(timezone.utc)
    expected = compute_signal_id("PETR4", "BUY", 30.0, 33.0, 28.5, VALID_SHA256, now)
    sig = TypedSignal.model_validate({
        "signal_id": expected,
        "ticker": "PETR4",
        "side": "BUY",
        "price": 30.0,
        "target_price": 33.0,
        "stop_loss": 28.5,
        "reason": "Breakout",
        "generated_at": now,
        "dataset_sha256": VALID_SHA256,
        "dataset_approved": True,
    })
    assert sig.signal_id == expected


def test_caller_supplied_mismatched_signal_id():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="signal_id mismatch"):
        TypedSignal.model_validate({
            "signal_id": "sig_" + "f" * 64,
            "ticker": "PETR4",
            "side": "BUY",
            "price": 30.0,
            "target_price": 33.0,
            "stop_loss": 28.5,
            "reason": "Breakout",
            "generated_at": now,
            "dataset_sha256": VALID_SHA256,
            "dataset_approved": True,
        })


def test_reject_bool_as_numeric():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        TypedSignal.model_validate({
            "ticker": "PETR4",
            "side": "BUY",
            "price": True,
            "target_price": 33.0,
            "stop_loss": 28.5,
            "reason": "Test",
            "generated_at": now,
            "dataset_sha256": VALID_SHA256,
            "dataset_approved": True,
        })


@pytest.mark.parametrize("val", [float("nan"), float("inf"), float("-inf")])
def test_reject_nan_inf(val):
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        TypedSignal.model_validate({
            "ticker": "PETR4",
            "side": "BUY",
            "price": val,
            "target_price": 33.0,
            "stop_loss": 28.5,
            "reason": "Test",
            "generated_at": now,
            "dataset_sha256": VALID_SHA256,
            "dataset_approved": True,
        })


@pytest.mark.parametrize("p", [0.0, -10.0])
def test_reject_zero_or_negative_price(p):
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        TypedSignal.model_validate({
            "ticker": "PETR4",
            "side": "BUY",
            "price": p,
            "target_price": 33.0,
            "stop_loss": 28.5,
            "reason": "Test",
            "generated_at": now,
            "dataset_sha256": VALID_SHA256,
            "dataset_approved": True,
        })


def test_reject_naive_timestamp():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(ValueError, match="generated_at must be timezone-aware"):
        TypedSignal.model_validate({
            "ticker": "PETR4",
            "side": "BUY",
            "price": 30.0,
            "target_price": 33.0,
            "stop_loss": 28.5,
            "reason": "Test",
            "generated_at": naive,
            "dataset_sha256": VALID_SHA256,
            "dataset_approved": True,
        })


def test_reject_invalid_side():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        TypedSignal.model_validate({
            "ticker": "PETR4",
            "side": "INVALID_SIDE",
            "price": 30.0,
            "target_price": 33.0,
            "stop_loss": 28.5,
            "reason": "Test",
            "generated_at": now,
            "dataset_sha256": VALID_SHA256,
            "dataset_approved": True,
        })


def test_reject_buy_inverted_target_stop():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="BUY requires stop_loss < price < target_price"):
        TypedSignal.model_validate({
            "ticker": "PETR4",
            "side": "BUY",
            "price": 30.0,
            "target_price": 28.0,  # Inverted!
            "stop_loss": 32.0,    # Inverted!
            "reason": "Test",
            "generated_at": now,
            "dataset_sha256": VALID_SHA256,
            "dataset_approved": True,
        })


def test_reject_sell_inverted_target_stop():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="SELL requires target_price < price < stop_loss"):
        TypedSignal.model_validate({
            "ticker": "PETR4",
            "side": "SELL",
            "price": 30.0,
            "target_price": 33.0,  # Inverted!
            "stop_loss": 28.0,    # Inverted!
            "reason": "Test",
            "generated_at": now,
            "dataset_sha256": VALID_SHA256,
            "dataset_approved": True,
        })


def test_reject_unapproved_dataset():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="Invalid or unapproved dataset_sha256"):
        TypedSignal.model_validate({
            "ticker": "PETR4",
            "side": "BUY",
            "price": 30.0,
            "target_price": 33.0,
            "stop_loss": 28.5,
            "reason": "Test",
            "generated_at": now,
            "dataset_sha256": "1" * 64,  # Not approved in fixture
            "dataset_approved": True,
        })


def test_reject_dataset_approved_false():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="Strategy signal dataset must be approved"):
        TypedSignal.model_validate({
            "ticker": "PETR4",
            "side": "BUY",
            "price": 30.0,
            "target_price": 33.0,
            "stop_loss": 28.5,
            "reason": "Test",
            "generated_at": now,
            "dataset_sha256": VALID_SHA256,
            "dataset_approved": False,
        })


def test_reject_extra_fields():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        TypedSignal.model_validate({
            "ticker": "PETR4",
            "side": "BUY",
            "price": 30.0,
            "target_price": 33.0,
            "stop_loss": 28.5,
            "reason": "Test",
            "generated_at": now,
            "dataset_sha256": VALID_SHA256,
            "dataset_approved": True,
            "extra_forged_field": "injected",
        })


def test_signal_id_sensitivity():
    now = datetime.now(timezone.utc)
    base = {
        "ticker": "PETR4",
        "side": "BUY",
        "price": 30.0,
        "target_price": 33.0,
        "stop_loss": 28.5,
        "reason": "Test",
        "generated_at": now,
        "dataset_sha256": VALID_SHA256,
        "dataset_approved": True,
    }
    sig1 = TypedSignal.model_validate(base)

    # Change ticker
    sig2 = TypedSignal.model_validate({**base, "ticker": "VALE3"})
    assert sig1.signal_id != sig2.signal_id

    # Change price
    sig3 = TypedSignal.model_validate({**base, "price": 30.5})
    assert sig1.signal_id != sig3.signal_id

    # Change target
    sig4 = TypedSignal.model_validate({**base, "target_price": 34.0})
    assert sig1.signal_id != sig4.signal_id

    # Change stop
    sig5 = TypedSignal.model_validate({**base, "stop_loss": 29.0})
    assert sig1.signal_id != sig5.signal_id
