import hashlib
import json
import os
from pathlib import Path
from typing import Literal

import pandas as pd
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


def require_dataset_approval_by_digest(
    dataset_sha256: str,
    registry_path: Path | str | None = None,
    project_root: Path | str | None = None,
) -> Approval:
    """Exact 64-hex digest, exact one registry match, revalidated evidence hashes. Fail closed."""
    if (
        not isinstance(dataset_sha256, str)
        or len(dataset_sha256) != 64
        or not all(c in '0123456789abcdef' for c in dataset_sha256)
    ):
        raise ValueError("data_approval_required")
    try:
        reg_file = Path(registry_path).resolve() if registry_path is not None else REGISTRY
        root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT.resolve()
        registry = Registry.model_validate_json(reg_file.read_bytes())
        matches = [a for a in registry.approvals if a.dataset_sha256 == dataset_sha256]
        if len(matches) != 1:
            raise ValueError('missing_or_ambiguous_approval')
        approval = matches[0]
        for name in ('source', 'calendar', 'adjustments', 'point_in_time'):
            evidence = getattr(approval, name)
            relative = Path(evidence.path)
            if relative.is_absolute():
                raise ValueError('absolute_evidence_path')
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError('evidence_outside_project')
            if hashlib.sha256(path.read_bytes()).hexdigest() != evidence.sha256:
                raise ValueError('evidence_changed')
        return approval
    except Exception:
        raise ValueError('data_approval_required') from None


def validate_dataset_digest(
    digest: str,
    registry_path: Path | str | None = None,
    project_root: Path | str | None = None,
) -> None:
    if registry_path is not None or project_root is not None:
        require_dataset_approval_by_digest(
            digest, registry_path=registry_path, project_root=project_root
        )
    else:
        require_dataset_approval_by_digest(digest)


def require_data_approval(
    df,
    ticker,
    registry_path: Path | str | None = None,
    project_root: Path | str | None = None,
) -> Approval:
    """No approval from dataframe attrs/kwargs; no implicit slice approvals."""
    try:
        digest = dataset_digest(df, ticker)
        if registry_path is not None or project_root is not None:
            return require_dataset_approval_by_digest(
                digest, registry_path=registry_path, project_root=project_root
            )
        return require_dataset_approval_by_digest(digest)
    except Exception:
        raise ValueError('data_approval_required') from None


def normalize_ohlcv_to_signal_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw market OHLCV DataFrame into exact signal dataframe for compute_signal and dataset_digest.

    Shared production transformation between MarketAnalyst and approval candidate builder.
    Expected raw columns: 'date' (or 'datetime'), 'open', 'high', 'low', 'close', 'volume'.
    Target schema: 'ts' (date), 'adj_close' (float), 'o' (float), 'c' (float), 'h' (float), 'l' (float), 'v' (float).
    Idempotent: if already in signal schema ('ts', 'adj_close', 'o', 'c', 'h', 'l', 'v'), validates and returns it.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        raise ValueError("empty_or_invalid_ohlcv_dataframe")

    signal_fields = ["ts", "adj_close", "o", "c", "h", "l", "v"]
    if all(col in df.columns for col in signal_fields):
        eng_df = df[signal_fields].copy()
        eng_df["ts"] = pd.to_datetime(eng_df["ts"]).dt.date
        for c in ("adj_close", "o", "c", "h", "l", "v"):
            eng_df[c] = eng_df[c].astype(float)
        validate_signal_input(eng_df)
        return eng_df

    date_col = None
    for cand in ("date", "Date", "datetime", "Datetime"):
        if cand in df.columns:
            date_col = cand
            break
    if date_col is None:
        raise ValueError("missing_date_column")

    col_map = {}
    for standard in ("open", "high", "low", "close", "volume"):
        found = None
        for cand in (standard, standard.capitalize(), standard.upper()):
            if cand in df.columns:
                found = cand
                break
        if found is None:
            raise ValueError(f"missing_{standard}_column")
        col_map[standard] = found

    eng_df = pd.DataFrame(
        {
            "ts": pd.to_datetime(df[date_col]).dt.date,
            "adj_close": df[col_map["close"]].astype(float),
            "o": df[col_map["open"]].astype(float),
            "c": df[col_map["close"]].astype(float),
            "h": df[col_map["high"]].astype(float),
            "l": df[col_map["low"]].astype(float),
            "v": df[col_map["volume"]].astype(float),
        }
    )
    validate_signal_input(eng_df)
    return eng_df


def save_registry(registry: Registry, registry_path: Path = REGISTRY) -> None:
    """Atomic write of registry JSON with fsync and safe tempfile replacement."""
    registry_path = Path(registry_path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = registry_path.with_name(f"{registry_path.name}.tmp.{os.getpid()}")
    try:
        content = registry.model_dump_json(indent=2) + "\n"
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, registry_path)
    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass
