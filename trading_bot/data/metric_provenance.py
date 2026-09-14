"""Deterministic publication gate. Local hashes do not establish authenticity.

The administrator controls the separate approval registry. This module neither
creates approvals nor authenticates reviewers; it must not be given a registry
chosen or writable by an untrusted metric producer. Not connected to execution.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MetricRecord(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    metric_name: str = Field(min_length=1)
    value: float | None
    unit: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    collected_at: datetime
    computed_at: datetime
    owner: str = Field(min_length=1)
    method_version: str = Field(min_length=1)
    verification_status: Literal["unverified", "verified", "unavailable"] = "unverified"
    reason: str | None = None

    @field_validator("source_ref", mode="before")
    def normalize_source_ref(cls, v: Any) -> str:
        if isinstance(v, (str, Path)):
            return Path(v).as_posix()
        return v

    @model_validator(mode="after")
    def validate_timeline(self):
        times = (self.observed_at, self.collected_at, self.computed_at)
        if any(t.tzinfo is None or t.utcoffset() is None for t in times):
            raise ValueError("timezone_required")
        if not self.observed_at <= self.collected_at <= self.computed_at:
            raise ValueError("invalid_timeline")
        if any(not getattr(self, key).strip() for key in ("metric_name", "unit", "source_ref", "owner", "method_version")):
            raise ValueError("empty_identity")
        return self


class MetricApproval(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    metric_name: str = Field(min_length=1)
    metric_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_by: str = Field(min_length=1)
    reviewed_at: datetime
    status: Literal["approved"]


class MetricApprovalRegistry(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    version: Literal[1]
    approvals: list[MetricApproval]


def metric_digest(record: MetricRecord) -> str:
    """Bind approval to the exact value, method, source and temporal identity."""
    data = record.model_dump(mode="json", exclude={"verification_status", "reason"})
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class MetricProvenanceAgent:
    def __init__(self, project_root: Path, registry_path: Path | None = None):
        self.root = Path(project_root).resolve()
        self.registry_path = Path(registry_path) if registry_path is not None else self.root / "config/metric_approvals.json"

    def evaluate(self, payload: dict, *, now: datetime | None = None) -> dict:
        """Return unavailable on any invalid/missing evidence, never impute values."""
        record = None
        reason = "invalid_metric_contract"
        try:
            record = MetricRecord.model_validate(payload)
            instant = now if now is not None else datetime.now(timezone.utc)
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise ValueError("invalid_clock")
            reason = "missing_value_or_future_timestamp"
            if record.value is None or record.computed_at > instant:
                raise ValueError(reason)
            reason = "invalid_or_changed_source"
            relative = Path(record.source_ref)
            path = (self.root / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(self.root) or path == self.registry_path.resolve():
                raise ValueError(reason)
            if hashlib.sha256(path.read_bytes()).hexdigest() != record.source_sha256:
                raise ValueError(reason)
            reason = "independent_approval_required"
            registry = MetricApprovalRegistry.model_validate_json(self.registry_path.read_bytes())
            matches = [
                item for item in registry.approvals
                if item.metric_sha256 == metric_digest(record)
                and item.metric_name == record.metric_name
            ]
            if len(matches) != 1:
                raise ValueError(reason)
            approval = matches[0]
            if (not approval.reviewed_by.strip()
                    or approval.reviewed_by.strip().casefold() == record.owner.strip().casefold()
                    or approval.reviewed_at.tzinfo is None or approval.reviewed_at.utcoffset() is None
                    or not record.computed_at <= approval.reviewed_at <= instant):
                raise ValueError(reason)
            return {**record.model_dump(mode="json"), "verification_status": "verified", "reason": None}
        except Exception:
            # Invalid input is not echoed; valid metadata stays available for audit.
            metadata = record.model_dump(mode="json") if record is not None else {key: None for key in MetricRecord.model_fields}
            return {**metadata, "value": None, "verification_status": "unavailable", "reason": reason}
