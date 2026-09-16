import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

import numpy as np
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
    """Persisted Human-Review Approval Authority (NEXUS-003-R2).

    Binds the full candidate capture authority:
    - candidate_id (64 hex characters)
    - ticker and strategy_id
    - intended_use == 'PAPER_TRADING'
    - dataset_sha256 (64 hex characters) and collected_at_utc
    - 6 verified evidence artifacts: canonical dataset.json, review dataset.csv,
      source.json, calendar.json, adjustments.json, point_in_time.json
    - human reviewer name, notes, and approved status
    """
    model_config = ConfigDict(strict=True, extra='forbid')
    candidate_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    ticker: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    intended_use: Literal['PAPER_TRADING'] = 'PAPER_TRADING'
    dataset_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    collected_at_utc: str = Field(min_length=1)
    dataset_artifact: Evidence
    review_csv: Evidence
    source: Evidence
    calendar: Evidence
    adjustments: Evidence
    point_in_time: Evidence
    reviewed_by: str = Field(min_length=1)
    review_notes: str = Field(min_length=1)
    status: Literal['approved'] = 'approved'


class Registry(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    version: Literal[1]
    approvals: list[Approval]


def compute_candidate_id(
    ticker: str,
    strategy_id: str,
    dataset_sha256: str,
    dataset_artifact_sha: str | None = None,
    review_csv_sha: str | None = None,
    source_sha: str | None = None,
    calendar_sha: str | None = None,
    adjustments_sha: str | None = None,
    pit_sha: str | None = None,
    collected_at_utc: str = "",
    intended_use: str = "PAPER_TRADING",
    **kwargs: Any,
) -> str:
    """Compute deterministic 64-hex SHA-256 binding all candidate evidence hashes and metadata."""
    art_sha = dataset_artifact_sha or kwargs.get("dataset_artifact_sha256", "")
    rev_sha = review_csv_sha or kwargs.get("review_csv_sha256", "")
    src_sha = source_sha or kwargs.get("source_sha256", "")
    cal_sha = calendar_sha or kwargs.get("calendar_sha256", "")
    adj_sha = adjustments_sha or kwargs.get("adjustments_sha256", "")
    p_sha = pit_sha or kwargs.get("point_in_time_sha256", "")

    payload = {
        "adjustments_sha256": adj_sha,
        "calendar_sha256": cal_sha,
        "collected_at_utc": collected_at_utc,
        "dataset_artifact_sha256": art_sha,
        "dataset_sha256": dataset_sha256,
        "point_in_time_sha256": p_sha,
        "review_csv_sha256": rev_sha,
        "source_sha256": src_sha,
        "strategy_id": strategy_id,
        "ticker": ticker,
    }
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


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
    settings_path: Path | str | None = None,
) -> Approval:
    """Exact 64-hex digest, exact one registry match, revalidated evidence hashes
    and full candidate binding. Fail closed.
    """
    if (
        not isinstance(dataset_sha256, str)
        or len(dataset_sha256) != 64
        or not all(c in '0123456789abcdef' for c in dataset_sha256.lower())
    ):
        raise ValueError("data_approval_required")
    try:
        reg_file = Path(registry_path).resolve() if registry_path is not None else REGISTRY
        root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT.resolve()
        if not reg_file.is_file():
            raise ValueError("data_approval_required")

        registry = Registry.model_validate_json(reg_file.read_bytes())
        matches = [a for a in registry.approvals if a.dataset_sha256.lower() == dataset_sha256.lower()]
        if len(matches) != 1:
            raise ValueError("missing_or_ambiguous_approval")
        approval = matches[0]

        # 1. Verify intended use and status
        if approval.intended_use != "PAPER_TRADING" or approval.status != "approved":
            raise ValueError("invalid_approval_scope")

        # 2. Verify strategy identity against active production strategy configuration
        from trading_bot.signals.strategy_identity import get_active_strategy_id
        active_strat = get_active_strategy_id(settings_path=settings_path)
        if approval.strategy_id != active_strat:
            raise ValueError("strategy_id_mismatch")

        # 3. Verify all 6 evidence files exist, remain within project root, and match byte hashes
        for name in (
            "source",
            "calendar",
            "adjustments",
            "point_in_time",
            "dataset_artifact",
            "review_csv",
        ):
            evidence = getattr(approval, name)
            if not evidence or not isinstance(evidence, Evidence):
                raise ValueError("missing_evidence_attribute")
            relative = Path(evidence.path)
            if relative.is_absolute():
                raise ValueError("absolute_evidence_path")
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError("evidence_outside_project")
            if not path.is_file():
                raise ValueError("evidence_file_missing")
            if hashlib.sha256(path.read_bytes()).hexdigest() != evidence.sha256:
                raise ValueError("evidence_changed")

        # 4. Recompute candidate_id and verify exact match against persisted authority
        recomputed_cand_id = compute_candidate_id(
            ticker=approval.ticker,
            strategy_id=approval.strategy_id,
            dataset_sha256=approval.dataset_sha256,
            dataset_artifact_sha=approval.dataset_artifact.sha256,
            review_csv_sha=approval.review_csv.sha256,
            source_sha=approval.source.sha256,
            calendar_sha=approval.calendar.sha256,
            adjustments_sha=approval.adjustments.sha256,
            pit_sha=approval.point_in_time.sha256,
            collected_at_utc=approval.collected_at_utc,
        )
        if recomputed_cand_id != approval.candidate_id:
            raise ValueError("candidate_id_mismatch")

        # 5. Semantic cross-checks on canonical dataset.json, review_csv, and point_in_time
        ds_path = (root / Path(approval.dataset_artifact.path)).resolve()
        ds_obj = json.loads(ds_path.read_text(encoding="utf-8"))
        if not isinstance(ds_obj, dict) or ds_obj.get("ticker") != approval.ticker:
            raise ValueError("dataset_ticker_mismatch")
        bars = ds_obj.get("bars", [])
        if not bars:
            raise ValueError("empty_dataset_bars")
        reloaded_df = pd.DataFrame(bars)
        norm_df = normalize_ohlcv_to_signal_df(reloaded_df)
        if dataset_digest(norm_df, approval.ticker) != approval.dataset_sha256:
            raise ValueError("dataset_digest_mismatch")

        csv_path = (root / Path(approval.review_csv.path)).resolve()
        csv_df = pd.read_csv(csv_path)
        if len(csv_df) != len(norm_df):
            raise ValueError("review_csv_length_mismatch")
        norm_csv_df = normalize_ohlcv_to_signal_df(csv_df)
        for col in ("adj_close", "o", "c", "h", "l", "v"):
            orig_vals = norm_df[col].astype(float).values
            csv_vals = norm_csv_df[col].astype(float).values
            if not np.allclose(orig_vals, csv_vals, rtol=1e-5, atol=1e-5):
                raise ValueError("review_csv_content_mismatch")

        pit_path = (root / Path(approval.point_in_time.path)).resolve()
        pit_obj = json.loads(pit_path.read_text(encoding="utf-8"))
        if (
            pit_obj.get("ticker") != approval.ticker
            or pit_obj.get("dataset_sha256") != approval.dataset_sha256
            or pit_obj.get("artifact_sha256") != approval.dataset_artifact.sha256
            or pit_obj.get("artifact_path") != approval.dataset_artifact.path
            or pit_obj.get("collected_at_utc") != approval.collected_at_utc
        ):
            raise ValueError("pit_semantic_mismatch")

        return approval
    except Exception:
        raise ValueError("data_approval_required") from None


def validate_dataset_digest(
    digest: str,
    registry_path: Path | str | None = None,
    project_root: Path | str | None = None,
    settings_path: Path | str | None = None,
) -> None:
    if registry_path is not None or project_root is not None or settings_path is not None:
        require_dataset_approval_by_digest(
            digest,
            registry_path=registry_path,
            project_root=project_root,
            settings_path=settings_path,
        )
    else:
        require_dataset_approval_by_digest(digest)


def require_data_approval(
    df,
    ticker,
    registry_path: Path | str | None = None,
    project_root: Path | str | None = None,
    settings_path: Path | str | None = None,
) -> Approval:
    """No approval from dataframe attrs/kwargs; no implicit slice approvals."""
    try:
        digest = dataset_digest(df, ticker)
        if registry_path is not None or project_root is not None or settings_path is not None:
            return require_dataset_approval_by_digest(
                digest,
                registry_path=registry_path,
                project_root=project_root,
                settings_path=settings_path,
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
