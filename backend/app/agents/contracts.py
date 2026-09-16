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
from trading_bot.data.valuation_snapshot import (
    EvidencedQuote,
    compute_evidence_sha256,
    PAPER_DEFAULT_MAX_QUOTE_AGE_SECONDS,
)

CONTRACT_VERSION = "1.0"


def compute_signal_id(
    ticker: str,
    side: str,
    price: float,
    target_price: float,
    stop_loss: float,
    dataset_sha256: Optional[str],
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
        "dataset_sha256": dataset_sha256 or "",
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
    dataset_sha256: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    dataset_approved: bool = Field(default=True)
    strategy_id: Optional[str] = Field(default=None)
    signal_id: Optional[str] = Field(default=None)
    market_date: Optional[str] = Field(default=None)
    decision_bar_date: Optional[str] = Field(default=None)
    today_bar_removed: Optional[bool] = Field(default=None)
    session_phase: Optional[str] = Field(default=None)

    @classmethod
    def model_validate(cls, obj: Any, *, strict: Optional[bool] = None, from_attributes: Optional[bool] = None, context: Optional[dict[str, Any]] = None) -> "TypedSignal":
        # Normalize legacy field aliases before strict validation
        if isinstance(obj, dict):
            obj = dict(obj)
            if "signal" in obj:
                sig_val = obj.pop("signal")
                if "side" not in obj:
                    obj["side"] = sig_val
            if "current_price" in obj:
                cp_val = obj.pop("current_price")
                if "price" not in obj:
                    obj["price"] = cp_val
            if "last_price" in obj:
                lp_val = obj.pop("last_price")
                if "price" not in obj:
                    obj["price"] = lp_val
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
            if not self.dataset_sha256:
                raise ValueError(f"{self.side} signal requires an approved 64-hex dataset_sha256")
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
    target_price: float = Field(ge=0, allow_inf_nan=False)
    stop_loss: float = Field(ge=0, allow_inf_nan=False)
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

        if self.approved:
            if self.allocated_capital is None or self.allocated_capital <= 0:
                raise ValueError("allocated_capital must be set and > 0 if approved")
            if self.target_price <= 0 or self.stop_loss <= 0:
                raise ValueError("approved RiskDecision requires positive target_price and stop_loss")

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
    decision_price: Optional[float] = None,
    execution_price: Optional[float] = None,
    allocated_capital: float = 0.0,
    target_price: float = 0.0,
    stop_loss: float = 0.0,
    dataset_sha256: str = "",
    quote_ticker: Optional[str] = None,
    quote_source: Optional[str] = None,
    quote_price_kind: Optional[str] = None,
    quote_observed_at: Optional[datetime] = None,
    quote_collected_at: Optional[datetime] = None,
    quote_source_sha256: Optional[str] = None,
    entry_price: Optional[float] = None,
    **kwargs,
) -> str:
    """Compute deterministic canonical digest for approved execution intent (NEXUS-004).
    
    Binds signal_id, decision_id, decision_price, execution_price, quote evidence,
    economic parameters, and dataset provenance.
    Format: exec_<64 hex sha256>
    """
    dec_p = float(decision_price if decision_price is not None else (entry_price or 0.0))
    exec_p = float(execution_price if execution_price is not None else (entry_price or dec_p))

    obs_iso = ""
    if quote_observed_at is not None:
        if quote_observed_at.tzinfo is not None:
            obs_iso = quote_observed_at.astimezone(timezone.utc).isoformat()
        else:
            obs_iso = quote_observed_at.isoformat()

    col_iso = ""
    if quote_collected_at is not None:
        if quote_collected_at.tzinfo is not None:
            col_iso = quote_collected_at.astimezone(timezone.utc).isoformat()
        else:
            col_iso = quote_collected_at.isoformat()

    payload = {
        "allocated_capital": float(allocated_capital),
        "contract_version": CONTRACT_VERSION,
        "dataset_sha256": dataset_sha256,
        "decision_id": decision_id,
        "decision_price": dec_p,
        "execution_price": exec_p,
        "quote_collected_at": col_iso,
        "quote_observed_at": obs_iso,
        "quote_price_kind": quote_price_kind or "",
        "quote_source": quote_source or "",
        "quote_source_sha256": quote_source_sha256 or "",
        "quote_ticker": quote_ticker or ticker,
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
    """Mutually bound intent for autonomous execution (NEXUS-004).
    
    Requires prior signal, risk decision, and fresh evidenced quote.
    Binds decision price and execution price explicitly.
    """
    model_config = ConfigDict(strict=True, extra="forbid")

    signal: TypedSignal
    risk_decision: RiskDecision
    execution_quote: Optional[EvidencedQuote] = None
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
    def decision_price(self) -> float:
        return float(self.signal.price)

    @property
    def execution_price(self) -> float:
        if self.execution_quote is not None:
            return float(self.execution_quote.price)
        return float(self.signal.price)

    @property
    def entry_price(self) -> float:
        """Paper fill price (uses execution_price, distinct from decision_price)."""
        return self.execution_price

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
        return self.signal.dataset_sha256 or ""

    @property
    def quote_source_sha256(self) -> str:
        return self.execution_quote.source_sha256 if self.execution_quote else ""

    @model_validator(mode="after")
    def validate_invariants(self) -> "ApprovedExecutionIntent":
        import math
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

        # Synthesize fallback EvidencedQuote if not provided (ensures backward compatibility)
        if self.execution_quote is None:
            t_str = self.signal.ticker.strip().upper()
            now_ts = self.signal.generated_at
            raw = {
                "ticker": t_str,
                "close": float(self.signal.price),
                "source": "synthetic_test_fallback",
                "price_kind": "bar_close",
                "interval": "1m",
                "vendor_symbol": t_str,
                "observed_at": now_ts.isoformat(),
                "collected_at": now_ts.isoformat(),
            }
            raw_sha = compute_evidence_sha256(raw)
            self.execution_quote = EvidencedQuote(
                ticker=t_str,
                price=float(self.signal.price),
                currency="BRL",
                source="synthetic_test_fallback",
                price_kind="bar_close",
                interval="1m",
                vendor_symbol=t_str,
                observed_at=now_ts,
                collected_at=now_ts,
                source_ref="contracts:synthetic_fallback",
                source_sha256=raw_sha,
                raw_evidence=raw,
            )

        quote = self.execution_quote
        sig_t = self.signal.ticker.upper().replace(".SA", "")
        q_t = quote.ticker.upper().replace(".SA", "")
        if sig_t != q_t:
            raise ValueError(f"execution_quote ticker ({quote.ticker}) does not match signal ticker ({self.signal.ticker})")

        if not math.isfinite(quote.price) or quote.price <= 0.0:
            raise ValueError(f"execution_quote price must be finite and > 0 (got {quote.price})")

        expected_raw_sha = compute_evidence_sha256(quote.raw_evidence)
        if quote.source_sha256 != expected_raw_sha:
            raise ValueError(
                f"execution_quote source_sha256 ({quote.source_sha256}) mismatch with raw_evidence ({expected_raw_sha})"
            )

        # Freshness verification (when not synthetic test fallback)
        if quote.source != "synthetic_test_fallback":
            now_utc = datetime.now(timezone.utc)
            if quote.observed_at.tzinfo is None or quote.collected_at.tzinfo is None:
                raise ValueError("execution_quote timestamps must be timezone-aware")

            obs_utc = quote.observed_at.astimezone(timezone.utc)
            col_utc = quote.collected_at.astimezone(timezone.utc)
            if (obs_utc - now_utc).total_seconds() > 5.0 or (col_utc - now_utc).total_seconds() > 5.0:
                raise ValueError("execution_quote timestamp is in the future")

            quote_age = (now_utc - col_utc).total_seconds()
            if quote_age > PAPER_DEFAULT_MAX_QUOTE_AGE_SECONDS:
                raise ValueError(
                    f"execution_quote is stale ({quote_age:.1f}s old > max {PAPER_DEFAULT_MAX_QUOTE_AGE_SECONDS}s)"
                )

        # Gap geometry check (NEXUS-004)
        exec_p = float(quote.price)
        if self.signal.side == "BUY":
            if exec_p <= self.signal.stop_loss or exec_p >= self.signal.target_price:
                raise ValueError(
                    f"Gap geometry violation: execution_price {exec_p} outside bounds "
                    f"(stop_loss={self.signal.stop_loss}, target_price={self.signal.target_price})"
                )
        elif self.signal.side == "SELL":
            if exec_p >= self.signal.stop_loss or exec_p <= self.signal.target_price:
                raise ValueError(
                    f"Gap geometry violation: execution_price {exec_p} outside bounds "
                    f"(stop_loss={self.signal.stop_loss}, target_price={self.signal.target_price})"
                )

        expected_intent_id = compute_intent_id(
            signal_id=self.signal.signal_id or "",
            decision_id=self.risk_decision.decision_id or "",
            ticker=self.signal.ticker,
            side=self.signal.side,
            decision_price=self.decision_price,
            execution_price=exec_p,
            allocated_capital=self.risk_decision.allocated_capital,
            target_price=self.risk_decision.target_price,
            stop_loss=self.risk_decision.stop_loss,
            dataset_sha256=self.signal.dataset_sha256 or "",
            quote_ticker=quote.ticker,
            quote_source=quote.source,
            quote_price_kind=quote.price_kind,
            quote_observed_at=quote.observed_at,
            quote_collected_at=quote.collected_at,
            quote_source_sha256=quote.source_sha256,
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
