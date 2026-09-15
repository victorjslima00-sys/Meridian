"""Local reviewed allowlist. Hashes bind evidence, not economic truth."""
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .signal_input import SignalBar, validate_signal_input

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = PROJECT_ROOT / 'config/data_approvals.json'


class Evidence(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class Approval(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    dataset_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    reviewed_by: str = Field(min_length=1)
    review_notes: str = Field(min_length=1)
    status: Literal['approved']
    source: Evidence
    calendar: Evidence
    adjustments: Evidence
    point_in_time: Evidence


class Registry(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    version: Literal[1]
    approvals: list[Approval]


def dataset_digest(df, ticker):
    validate_signal_input(df)
    if not isinstance(ticker, str) or not ticker.strip() or df.empty:
        raise ValueError('invalid_dataset_identity')
    bars = [SignalBar.model_validate(row).model_dump(mode='json')
            for row in df[list(SignalBar.model_fields)].to_dict('records')]
    payload = json.dumps({'ticker': ticker, 'bars': bars}, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def validate_dataset_digest(digest: str) -> None:
    if not isinstance(digest, str) or len(digest) != 64 or not all(c in '0123456789abcdef' for c in digest):
        raise ValueError("invalid_digest_format")
    try:
        registry = Registry.model_validate_json(REGISTRY.read_bytes())
        matches = [a for a in registry.approvals if a.dataset_sha256 == digest]
        if len(matches) != 1:
            raise ValueError('missing_or_ambiguous_approval')
        approval = matches[0]
        for name in ('source', 'calendar', 'adjustments', 'point_in_time'):
            evidence = getattr(approval, name)
            relative = Path(evidence.path)
            if relative.is_absolute():
                raise ValueError('absolute_evidence_path')
            path = (PROJECT_ROOT / relative).resolve()
            if not path.is_relative_to(PROJECT_ROOT.resolve()):
                raise ValueError('evidence_outside_project')
            if hashlib.sha256(path.read_bytes()).hexdigest() != evidence.sha256:
                raise ValueError('evidence_changed')
    except Exception:
        raise ValueError('data_approval_required') from None

def require_data_approval(df, ticker):
    """No approval from dataframe attrs/kwargs; no implicit slice approvals."""
    try:
        digest = dataset_digest(df, ticker)
        validate_dataset_digest(digest)
    except Exception:
        raise ValueError('data_approval_required') from None
