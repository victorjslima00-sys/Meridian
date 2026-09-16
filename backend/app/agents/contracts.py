"""Typed Signal -> Risk -> Paper Execution contracts (NEXUS-002).

Enforces strict schemas, deterministic cryptographic bindings, and fail-closed validation.
No raw dictionary may cross an execution-capable boundary without validation.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

import trading_bot.data.approval

CONTRACT_VERSION = "1.0"


def compute_signal_id(
    ticker: str,
    side: str,
    price: float,
    target_price: float,
    stop_loss: float,
    dataset_sha256: str,
    generated_at: datetime,
    strategy_id: Optional[str] = None,
) -> str:
    """Compute deterministic canonical digest binding economic & provenance identity.
    
    Format: sig_<64 hex sha256>
    """
    if generated_at.tzinfo is None or generated_at.tzinfo.utcoffset(generated_at) is None:
        raise ValueError("generated_at must be timezone-aware for signal identity")

    dt_utc = generated_at.astimezone(timezone.utc).isoformat()
    payload = {
        "contract_version": CONTRACT_VERSION,
        "dataset_sha256": dataset_sha256,
        "generated_at": dt_utc,
        "price": float(price),
        "side": side,
        "stop_loss": float(stop_loss),
        "strategy_id": strategy_id or "",
        "target_price": float(target_price),
        "ticker": ticker,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"sig_{digest}"


def compute_decision_id(
    signal_id: str,
    approved: bool,
    reason: str,
    allocated_capital: Optional[float],
    target_price: float,
    stop_loss: float,
    decision_timestamp: datetime,
) -> str:
    """Compute deterministic canonical digest for risk decision.
    
    Format: risk_<64 hex sha256>
    """
    if decision_timestamp.tzinfo is None or decision_timestamp.tzinfo.utcoffset(decision_timestamp) is None:
        raise ValueError("decision_timestamp must be timezone-aware for decision identity")

    dt_utc = decision_timestamp.astimezone(timezone.utc).isoformat()
    payload = {
        "allocated_capital": float(allocated_capital) if allocated_capital is not None else None,
        "approved": approved,
        "contract_version": CONTRACT_VERSION,
        "decision_timestamp": dt_utc,
        "reason": reason,
        "signal_id": signal_id,
        "stop_loss": float(stop_loss),
        "target_price": float(target_price),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"risk_{digest}"


class TypedSignal(BaseModel):
    """The smallest strict typed contract necessary for autonomous/strategy-generated signals."""
    model_config = ConfigDict(strict=True, extra="forbid")

    ticker: str = Field(min_length=1)
    side: Literal["BUY", "SELL", "HOLD"]
    price: float = Field(gt=0, allow_inf_nan=False)
    target_price: float = Field(ge=0, allow_inf_nan=False)
    stop_loss: float = Field(ge=0, allow_inf_nan=False)
    confidence: Optional[int] = Field(default=None, ge=0, le=100)
    reason: str = Field(min_length=1)
    generated_at: datetime
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_approved: bool = Field(default=True)
    strategy_id: Optional[str] = Field(default=None)
    signal_id: Optional[str] = Field(default=None)

    @classmethod
    def model_validate(cls, obj: Any, *, strict: Optional[bool] = None, from_attributes: Optional[bool] = None, context: Optional[dict[str, Any]] = None) -> "TypedSignal":
        # Normalize legacy field aliases before strict validation
        if isinstance(obj, dict):
            obj = dict(obj)
            if "signal" in obj and "side" not in obj:
                obj["side"] = obj.pop("signal")
            if "current_price" in obj and "price" not in obj:
                obj["price"] = obj.pop("current_price")
            elif "last_price" in obj and "price" not in obj:
                obj["price"] = obj.pop("last_price")
            if isinstance(obj.get("generated_at"), str):
                try:
                    obj["generated_at"] = datetime.fromisoformat(obj["generated_at"])
                except Exception:
                    pass
        return super().model_validate(obj, strict=strict, from_attributes=from_attributes, context=context)

    @property
    def signal(self) -> str:
        """Alias for backward compatibility."""
        return self.side

    @property
    def current_price(self) -> float:
        """Alias for backward compatibility."""
        return self.price

    @model_validator(mode="after")
    def validate_invariants(self) -> "TypedSignal":
        if self.generated_at.tzinfo is None or self.generated_at.tzinfo.utcoffset(self.generated_at) is None:
            raise ValueError("generated_at must be timezone-aware")

        if self.side == "BUY":
            if self.target_price <= 0 or self.stop_loss <= 0:
                raise ValueError("BUY requires positive target_price and stop_loss")
            if not (self.stop_loss < self.price < self.target_price):
                raise ValueError(
                    f"BUY requires stop_loss < price < target_price "
                    f"(stop={self.stop_loss}, price={self.price}, target={self.target_price})"
                )
        elif self.side == "SELL":
            if self.target_price <= 0 or self.stop_loss <= 0:
                raise ValueError("SELL requires positive target_price and stop_loss")
            if not (self.target_price < self.price < self.stop_loss):
                raise ValueError(
                    f"SELL requires target_price < price < stop_loss "
                    f"(target={self.target_price}, price={self.price}, stop={self.stop_loss})"
                )
        elif self.side == "HOLD":
            pass
        else:
            raise ValueError(f"Invalid side: {self.side}")

        if self.side != "HOLD":
            if not self.dataset_approved:
                raise ValueError("Strategy signal dataset must be approved")

            # Dataset approval verification
            try:
                trading_bot.data.approval.require_dataset_approval_by_digest(self.dataset_sha256)
            except Exception as e:
                raise ValueError("Invalid or unapproved dataset_sha256") from e

        # Recompute deterministic signal_id
        expected_id = compute_signal_id(
            ticker=self.ticker,
            side=self.side,
            price=self.price,
            target_price=self.target_price,
            stop_loss=self.stop_loss,
            dataset_sha256=self.dataset_sha256,
            generated_at=self.generated_at,
            strategy_id=self.strategy_id,
        )

        if self.signal_id is not None and self.signal_id != expected_id:
            raise ValueError(f"signal_id mismatch: caller provided {self.signal_id} but computed {expected_id}")

        self.signal_id = expected_id
        return self


# Backward-compatible alias
StrategySignal = TypedSignal


class RiskDecision(BaseModel):
    """Strict typed risk decision contract bound to a specific strategy signal."""
    model_config = ConfigDict(strict=True, extra="forbid")

    signal_id: str
    approved: bool
    reason: str
    allocated_capital: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    target_price: float = Field(gt=0, allow_inf_nan=False)
    stop_loss: float = Field(gt=0, allow_inf_nan=False)
    decision_timestamp: datetime
    decision_id: Optional[str] = Field(default=None)

    @classmethod
    def model_validate(cls, obj: Any, *, strict: Optional[bool] = None, from_attributes: Optional[bool] = None, context: Optional[dict[str, Any]] = None) -> "RiskDecision":
        if isinstance(obj, dict):
            obj = dict(obj)
            if "risk_decision_id" in obj and "decision_id" not in obj:
                obj["decision_id"] = obj.pop("risk_decision_id")
        return super().model_validate(obj, strict=strict, from_attributes=from_attributes, context=context)

    @model_validator(mode="after")
    def validate_invariants(self) -> "RiskDecision":
        if self.decision_timestamp.tzinfo is None or self.decision_timestamp.tzinfo.utcoffset(self.decision_timestamp) is None:
            raise ValueError("decision_timestamp must be timezone-aware")

        if self.approved and (self.allocated_capital is None or self.allocated_capital <= 0):
            raise ValueError("allocated_capital must be set and > 0 if approved")

        expected_decision_id = compute_decision_id(
            signal_id=self.signal_id,
            approved=self.approved,
            reason=self.reason,
            allocated_capital=self.allocated_capital,
            target_price=self.target_price,
            stop_loss=self.stop_loss,
            decision_timestamp=self.decision_timestamp,
        )

        if self.decision_id is not None and self.decision_id != expected_decision_id:
            raise ValueError(f"decision_id mismatch: caller provided {self.decision_id} but computed {expected_decision_id}")

        self.decision_id = expected_decision_id
        return self

    @property
    def risk_decision_id(self) -> str:
        """Alias for backward compatibility."""
        return self.decision_id or ""

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)

    def __getitem__(self, item: str) -> Any:
        if item == "risk_decision_id":
            return self.risk_decision_id
        return getattr(self, item)


def compute_intent_id(
    signal_id: str,
    decision_id: str,
    ticker: str,
    side: str,
    entry_price: float,
    allocated_capital: float,
    target_price: float,
    stop_loss: float,
    dataset_sha256: str,
) -> str:
    """Compute deterministic canonical digest for approved execution intent.
    
    Format: exec_<64 hex sha256>
    """
    payload = {
        "allocated_capital": float(allocated_capital),
        "contract_version": CONTRACT_VERSION,
        "dataset_sha256": dataset_sha256,
        "decision_id": decision_id,
        "entry_price": float(entry_price),
        "side": side,
        "signal_id": signal_id,
        "stop_loss": float(stop_loss),
        "target_price": float(target_price),
        "ticker": ticker,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"exec_{digest}"


class ApprovedExecutionIntent(BaseModel):
    """Mutually bound intent for autonomous execution. Requires prior signal and risk decision."""
    model_config = ConfigDict(strict=True, extra="forbid")

    signal: TypedSignal
    risk_decision: RiskDecision
    intent_id: Optional[str] = Field(default=None)

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: Optional[bool] = None,
        from_attributes: Optional[bool] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> "ApprovedExecutionIntent":
        return super().model_validate(obj, strict=strict, from_attributes=from_attributes, context=context)

    @property
    def signal_id(self) -> str:
        return self.signal.signal_id or ""

    @property
    def decision_id(self) -> str:
        return self.risk_decision.decision_id or ""

    @property
    def risk_decision_id(self) -> str:
        return self.decision_id

    @property
    def ticker(self) -> str:
        return self.signal.ticker

    @property
    def side(self) -> Literal["BUY", "SELL"]:
        return self.signal.side  # type: ignore

    @property
    def entry_price(self) -> float:
        return self.signal.price

    @property
    def allocated_capital(self) -> float:
        return self.risk_decision.allocated_capital or 0.0

    @property
    def target_price(self) -> float:
        return self.risk_decision.target_price

    @property
    def stop_loss(self) -> float:
        return self.risk_decision.stop_loss

    @property
    def dataset_sha256(self) -> str:
        return self.signal.dataset_sha256

    @model_validator(mode="after")
    def validate_invariants(self) -> "ApprovedExecutionIntent":
        if not self.risk_decision.approved:
            raise ValueError("risk_decision must be approved")
        if self.risk_decision.signal_id != self.signal.signal_id:
            raise ValueError(
                f"risk_decision.signal_id ({self.risk_decision.signal_id}) does not match "
                f"signal.signal_id ({self.signal.signal_id})"
            )
        if self.signal.side not in ("BUY", "SELL"):
            raise ValueError(f"signal.side must be BUY or SELL, not HOLD (got {self.signal.side})")
        if self.risk_decision.target_price != self.signal.target_price:
            raise ValueError(
                f"risk target ({self.risk_decision.target_price}) does not match "
                f"signal target ({self.signal.target_price})"
            )
        if self.risk_decision.stop_loss != self.signal.stop_loss:
            raise ValueError(
                f"risk stop ({self.risk_decision.stop_loss}) does not match "
                f"signal stop ({self.signal.stop_loss})"
            )
        if self.risk_decision.allocated_capital is None or self.risk_decision.allocated_capital <= 0:
            raise ValueError("allocated capital must be finite and > 0")

        expected_intent_id = compute_intent_id(
            signal_id=self.signal.signal_id or "",
            decision_id=self.risk_decision.decision_id or "",
            ticker=self.signal.ticker,
            side=self.signal.side,
            entry_price=self.signal.price,
            allocated_capital=self.risk_decision.allocated_capital,
            target_price=self.risk_decision.target_price,
            stop_loss=self.risk_decision.stop_loss,
            dataset_sha256=self.signal.dataset_sha256,
        )

        if self.intent_id is not None and self.intent_id != expected_intent_id:
            raise ValueError(f"intent_id mismatch: caller provided {self.intent_id} but computed {expected_intent_id}")

        self.intent_id = expected_intent_id
        return self


class ManualExecutionIntent(BaseModel):
    """Explicitly typed contract for authenticated human/manual actions.
    
    Never fabricates dataset_sha256 or signal_id.
    """
    model_config = ConfigDict(strict=True, extra="forbid")

    ticker: str = Field(min_length=1)
    side: Literal["BUY", "SELL"]
    entry_price: float = Field(gt=0, allow_inf_nan=False)
    allocated_capital: float = Field(gt=0, allow_inf_nan=False)
    target_price: float = Field(gt=0, allow_inf_nan=False)
    stop_loss: float = Field(gt=0, allow_inf_nan=False)
    reason: str = Field(min_length=1)
    operator: str = Field(default="manual")

    @model_validator(mode="after")
    def validate_invariants(self) -> "ManualExecutionIntent":
        if self.side == "BUY":
            if not (self.stop_loss < self.entry_price < self.target_price):
                raise ValueError("BUY requires stop_loss < entry_price < target_price")
        elif self.side == "SELL":
            if not (self.target_price < self.entry_price < self.stop_loss):
                raise ValueError("SELL requires target_price < entry_price < stop_loss")
        return self
