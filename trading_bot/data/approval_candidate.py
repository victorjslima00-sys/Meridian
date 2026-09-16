"""Approval Candidate Builder & Governance Gate (NEXUS-003-R1).

Produces auditable, deterministic candidate evidence bundles for paper trading datasets,
validates bundle integrity and tamper resistance, and exposes an explicit human approval
mechanism that modifies the registry only upon verified review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from backend.app.markets import resolve_market
from trading_bot.data.approval import (
    PROJECT_ROOT,
    REGISTRY,
    Approval,
    Evidence,
    Registry,
    compute_candidate_id,
    dataset_digest,
    normalize_ohlcv_to_signal_df,
    save_registry,
)
from trading_bot.data.signal_input import SignalBar
from trading_bot.signals.strategy_identity import (
    DEFAULT_STRATEGY_ID,
    get_active_strategy_id,
)

try:
    import yfinance as yf
    _YF_VERSION = getattr(yf, "__version__", "unknown")
except Exception:
    _YF_VERSION = "unavailable"

APPROVAL_CONFIRMATION_TOKEN = "APPROVE_DATASET_FOR_PAPER_TRADING_ONLY"

__all__ = [
    "APPROVAL_CONFIRMATION_TOKEN",
    "CandidateManifest",
    "DEFAULT_STRATEGY_ID",
    "approve_candidate",
    "build_candidate_bundle",
    "compute_candidate_id",
    "get_active_strategy_id",
    "main",
    "validate_candidate",
]


class CandidateManifest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    candidate_version: Literal[1] = 1
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    ticker: str = Field(min_length=1)
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategy_id: str = Field(min_length=1)
    source_provider: Literal["yfinance"] = "yfinance"
    period: str = Field(min_length=1)
    interval: str = Field(min_length=1)
    observed_range: Dict[str, str]
    collected_at_utc: str = Field(min_length=1)
    row_count: int = Field(gt=0)
    dataset_artifact: Evidence
    review_csv: Evidence
    source: Evidence
    calendar: Evidence
    adjustments: Evidence
    point_in_time: Evidence
    limitations: List[str] = Field(min_length=1)
    intended_use: Literal["PAPER_TRADING"] = "PAPER_TRADING"


def _rel_path_str(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def build_candidate_bundle(
    ticker: str,
    period: str = "2y",
    interval: str = "1d",
    output_dir: Optional[Path] = None,
    strategy_id: Optional[str] = None,
    project_root: Optional[Path] = None,
    settings_path: Optional[Path | str] = None,
    df: Optional[pd.DataFrame] = None,
) -> CandidateManifest:
    """Obtain dataset via production path, normalize into eng_df, and build evidence bundle.

    NEVER modifies config/data_approvals.json.
    NEVER marks anything approved automatically.
    """
    root = (project_root or PROJECT_ROOT).resolve()
    active_strat = get_active_strategy_id(settings_path=settings_path)
    effective_strat = strategy_id or active_strat
    if effective_strat != active_strat:
        raise ValueError(
            f"strategy_id_mismatch: requested '{effective_strat}' differs from active configuration '{active_strat}'"
        )

    collected_at = datetime.now(timezone.utc).isoformat()

    # 1. Obtain market data via exact production path unless pre-supplied
    if df is None:
        market = resolve_market(ticker)
        df = market.fetch_ohlcv(ticker, period=period, interval=interval)

    # 1b. Deterministic closed daily frame transformation (NEXUS-004)
    from trading_bot.data.closed_frame import closed_daily_signal_frame
    closed_res = closed_daily_signal_frame(df)
    closed_df = closed_res.df

    if closed_df is None or len(closed_df) < 201:
        count = len(closed_df) if closed_df is not None else 0
        raise ValueError(f"insufficient_ohlcv_data: got {count} bars, minimum 201 required")

    # 2. Extract deterministic signal dataframe using shared helper
    eng_df = normalize_ohlcv_to_signal_df(closed_df)

    # 3. Calculate canonical dataset digest
    d_sha = dataset_digest(eng_df, ticker)

    # 4. Prepare in-memory evidence payloads and byte hashes
    first_obs = str(eng_df["ts"].iloc[0])
    last_obs = str(eng_df["ts"].iloc[-1])
    row_count = len(eng_df)

    bars = [
        SignalBar.model_validate(row).model_dump(mode="json")
        for row in eng_df[list(SignalBar.model_fields)].to_dict("records")
    ]
    payload_dict = {"ticker": ticker, "bars": bars}
    dataset_json_str = json.dumps(payload_dict, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    dataset_json_bytes = dataset_json_str.encode("utf-8")
    dataset_artifact_sha = hashlib.sha256(dataset_json_bytes).hexdigest()

    csv_str = eng_df.to_csv(index=False)
    csv_bytes = csv_str.encode("utf-8")
    review_csv_sha = hashlib.sha256(csv_bytes).hexdigest()

    source_payload = {
        "provider": "yfinance",
        "vendor_symbol": ticker,
        "ticker_requested": ticker,
        "period": period,
        "interval": interval,
        "collected_at_utc": collected_at,
        "auto_adjust": True,
        "auto_adjust_semantics": (
            "yfinance auto_adjust=True; open, high, low, close adjusted by provider "
            "for corporate splits and dividend distributions; adj_close == close"
        ),
        "provider_version": _YF_VERSION,
        "row_count": row_count,
        "first_observation": first_obs,
        "last_observation": last_obs,
        "dataset_sha256": d_sha,
        "artifact_sha256": dataset_artifact_sha,
        "feed_type": "vendor_daily_bars",
        "official_exchange_feed": False,
        "disclaimer": (
            "Not official B3 tick/quote data, exchange tick, or NBBO. "
            "Sourced from yfinance historical daily bars."
        ),
    }
    source_bytes = (json.dumps(source_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    source_sha = hashlib.sha256(source_bytes).hexdigest()

    observed_dates = [str(d) for d in eng_df["ts"]]
    calendar_payload = {
        "ticker": ticker,
        "calendar_type": "observed_dataset_dates",
        "source_method": "yfinance historical daily trading observations",
        "is_official_b3_calendar": False,
        "disclaimer": (
            "No official B3 exchange holiday/trading calendar verification used; "
            "calendar reflects dates observed in provider dataset"
        ),
        "first_date": first_obs,
        "last_date": last_obs,
        "total_trading_days": row_count,
        "observed_dates": observed_dates,
        "dataset_sha256": d_sha,
    }
    calendar_bytes = (json.dumps(calendar_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    calendar_sha = hashlib.sha256(calendar_bytes).hexdigest()

    adjustments_payload = {
        "ticker": ticker,
        "auto_adjust": True,
        "provider_adjustment_semantics": (
            "yfinance auto_adjust=True: open, high, low, close adjusted for corporate splits "
            "and dividend distributions"
        ),
        "independent_corporate_action_verification": False,
        "disclaimer": (
            "Independent corporate-action / dividend verification is unavailable from this provider; "
            "provider vendor adjustments accepted as-is without exchange audit"
        ),
        "dataset_sha256": d_sha,
    }
    adjustments_bytes = (json.dumps(adjustments_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    adjustments_sha = hashlib.sha256(adjustments_bytes).hexdigest()

    # 5. Prepare candidate directory and relative paths
    safe_ticker = ticker.replace("^", "").replace(".", "_").replace("/", "_")
    if output_dir is not None:
        bundle_dir = Path(output_dir).resolve()
    else:
        bundle_dir = (root / "data" / "approval_candidates" / f"{safe_ticker}_{d_sha[:16]}").resolve()

    dataset_artifact_path = bundle_dir / "dataset.json"
    dataset_artifact_rel = _rel_path_str(dataset_artifact_path, root)

    # If bundle already exists, check if it's an idempotent re-run or conflicting candidate
    if bundle_dir.exists():
        manifest_existing_path = bundle_dir / "candidate_manifest.json"
        if manifest_existing_path.exists():
            try:
                m_existing = CandidateManifest.model_validate_json(manifest_existing_path.read_bytes())
                # If regenerating exact same dataset & strategy, preserve original capture timestamp
                if m_existing.dataset_sha256 == d_sha and m_existing.strategy_id == effective_strat:
                    collected_at = m_existing.collected_at_utc
                    source_payload["collected_at_utc"] = collected_at
                    source_bytes = (json.dumps(source_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
                    source_sha = hashlib.sha256(source_bytes).hexdigest()
            except Exception as exc:
                if "candidate_collision_error" in str(exc):
                    raise
                raise ValueError(f"candidate_collision_error: existing directory corrupted or conflicting: {exc}")

    pit_payload = {
        "ticker": ticker,
        "evidence_type": "capture_time_evidence",
        "collected_at_utc": collected_at,
        "dataset_sha256": d_sha,
        "artifact_path": dataset_artifact_rel,
        "artifact_sha256": dataset_artifact_sha,
        "historical_point_in_time_guarantee": False,
        "disclaimer": (
            "Capture-time snapshot only. Sourced at collected_at_utc. "
            "No point-in-time guarantee against post-hoc revisions, delistings, "
            "or corporate restatements by yfinance."
        ),
    }
    pit_bytes = (json.dumps(pit_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    pit_sha = hashlib.sha256(pit_bytes).hexdigest()

    # 6. Compute candidate_id binding all evidence hashes and capture timestamp
    cand_id = compute_candidate_id(
        ticker=ticker,
        strategy_id=effective_strat,
        dataset_sha256=d_sha,
        dataset_artifact_sha=dataset_artifact_sha,
        review_csv_sha=review_csv_sha,
        source_sha=source_sha,
        calendar_sha=calendar_sha,
        adjustments_sha=adjustments_sha,
        pit_sha=pit_sha,
        collected_at_utc=collected_at,
    )

    # 7. Collision check: do not overwrite existing candidate with conflicting bytes
    if bundle_dir.exists():
        manifest_existing_path = bundle_dir / "candidate_manifest.json"
        if manifest_existing_path.exists():
            try:
                m_existing = CandidateManifest.model_validate_json(manifest_existing_path.read_bytes())
                if m_existing.candidate_id != cand_id:
                    raise ValueError(
                        f"candidate_collision_error: directory {bundle_dir} contains conflicting candidate "
                        f"(existing candidate_id={m_existing.candidate_id}, new={cand_id})"
                    )
            except Exception as exc:
                if "candidate_collision_error" in str(exc):
                    raise
                raise ValueError(f"candidate_collision_error: existing directory corrupted or conflicting: {exc}")

    bundle_dir.mkdir(parents=True, exist_ok=True)

    (bundle_dir / "dataset.json").write_bytes(dataset_json_bytes)
    (bundle_dir / "dataset.csv").write_bytes(csv_bytes)
    (bundle_dir / "source.json").write_bytes(source_bytes)
    (bundle_dir / "calendar.json").write_bytes(calendar_bytes)
    (bundle_dir / "adjustments.json").write_bytes(adjustments_bytes)
    (bundle_dir / "point_in_time.json").write_bytes(pit_bytes)

    dataset_artifact_ev = Evidence(
        path=_rel_path_str(bundle_dir / "dataset.json", root),
        sha256=dataset_artifact_sha,
    )
    review_csv_ev = Evidence(
        path=_rel_path_str(bundle_dir / "dataset.csv", root),
        sha256=review_csv_sha,
    )
    source_ev = Evidence(
        path=_rel_path_str(bundle_dir / "source.json", root),
        sha256=source_sha,
    )
    calendar_ev = Evidence(
        path=_rel_path_str(bundle_dir / "calendar.json", root),
        sha256=calendar_sha,
    )
    adjustments_ev = Evidence(
        path=_rel_path_str(bundle_dir / "adjustments.json", root),
        sha256=adjustments_sha,
    )
    pit_ev = Evidence(
        path=_rel_path_str(bundle_dir / "point_in_time.json", root),
        sha256=pit_sha,
    )

    limitations = [
        "Provider data is yfinance, not official B3 tick/quote feed",
        "Adjustments provided by vendor without independent audit",
        "Capture-time snapshot without historical restatement protection",
    ]
    manifest = CandidateManifest(
        candidate_version=1,
        candidate_id=cand_id,
        ticker=ticker,
        dataset_sha256=d_sha,
        strategy_id=effective_strat,
        source_provider="yfinance",
        period=period,
        interval=interval,
        observed_range={"start": first_obs, "end": last_obs},
        collected_at_utc=collected_at,
        row_count=row_count,
        dataset_artifact=dataset_artifact_ev,
        review_csv=review_csv_ev,
        source=source_ev,
        calendar=calendar_ev,
        adjustments=adjustments_ev,
        point_in_time=pit_ev,
        limitations=limitations,
        intended_use="PAPER_TRADING",
    )

    manifest_file = bundle_dir / "candidate_manifest.json"
    manifest_file.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")

    # Self-validate immediately
    validate_candidate(manifest_file, project_root=root, settings_path=settings_path)

    return manifest


def validate_candidate(
    candidate_path: str | Path,
    project_root: Optional[Path] = None,
    settings_path: Optional[Path | str] = None,
) -> CandidateManifest:
    """Deterministic validator for candidate evidence bundles.

    Recomputes dataset_sha256, candidate_id, and every evidence file hash.
    Performs full semantic cross-checks on metadata and review CSV.
    Rejects missing files, changed files, path traversal/outside-project paths,
    ticker mismatch, altered dataset, or conflicting strategy/capture identity.
    """
    root = (project_root or PROJECT_ROOT).resolve()
    c_path = Path(candidate_path)
    if not c_path.is_absolute():
        c_path = (root / c_path).resolve()
    else:
        c_path = c_path.resolve()

    if not c_path.is_file():
        raise ValueError(f"candidate_manifest_not_found: {c_path}")

    if not c_path.is_relative_to(root):
        raise ValueError(f"candidate_outside_project: {c_path}")

    manifest_bytes = c_path.read_bytes()
    manifest = CandidateManifest.model_validate_json(manifest_bytes)

    # Verify strategy matches active strategy
    active_strat = get_active_strategy_id(settings_path=settings_path)
    if manifest.strategy_id != active_strat:
        raise ValueError(
            f"strategy_id_mismatch: candidate strategy '{manifest.strategy_id}' "
            f"does not match active strategy '{active_strat}'"
        )

    # Check each evidence path and recompute sha256
    evidence_map = {
        "dataset_artifact": manifest.dataset_artifact,
        "review_csv": manifest.review_csv,
        "source": manifest.source,
        "calendar": manifest.calendar,
        "adjustments": manifest.adjustments,
        "point_in_time": manifest.point_in_time,
    }

    for ev_name, ev in evidence_map.items():
        rel_path = Path(ev.path)
        if rel_path.is_absolute():
            raise ValueError(f"absolute_evidence_path: {ev_name} has {ev.path}")

        if any(part == ".." for part in rel_path.parts):
            raise ValueError(f"path_traversal_forbidden: {ev_name} has {ev.path}")

        file_path = (root / rel_path).resolve()
        if not file_path.is_relative_to(root):
            raise ValueError(f"evidence_outside_project: {ev_name} points to {file_path}")

        if not file_path.is_file():
            raise ValueError(f"missing_evidence_file: {ev_name} file not found: {file_path}")

        actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if actual_hash != ev.sha256:
            raise ValueError(f"evidence_hash_mismatch: {ev_name} expected {ev.sha256}, got {actual_hash}")

    # Re-verify candidate_id
    expected_cand_id = compute_candidate_id(
        ticker=manifest.ticker,
        strategy_id=manifest.strategy_id,
        dataset_sha256=manifest.dataset_sha256,
        dataset_artifact_sha=manifest.dataset_artifact.sha256,
        review_csv_sha=manifest.review_csv.sha256,
        source_sha=manifest.source.sha256,
        calendar_sha=manifest.calendar.sha256,
        adjustments_sha=manifest.adjustments.sha256,
        pit_sha=manifest.point_in_time.sha256,
        collected_at_utc=manifest.collected_at_utc,
    )
    if manifest.candidate_id != expected_cand_id:
        raise ValueError(
            f"candidate_id_mismatch: manifest candidate_id {manifest.candidate_id} != computed {expected_cand_id}"
        )

    # Re-read and recompute dataset_sha256 from canonical JSON
    ds_file = (root / Path(manifest.dataset_artifact.path)).resolve()
    raw_obj = json.loads(ds_file.read_text(encoding="utf-8"))
    if not isinstance(raw_obj, dict) or "bars" not in raw_obj or "ticker" not in raw_obj:
        raise ValueError("invalid_dataset_json_format")

    if raw_obj["ticker"] != manifest.ticker:
        raise ValueError(f"dataset_ticker_mismatch: json {raw_obj['ticker']} != manifest {manifest.ticker}")

    bars = raw_obj["bars"]
    if len(bars) != manifest.row_count:
        raise ValueError(f"dataset_row_count_mismatch: bars {len(bars)} != manifest {manifest.row_count}")

    if str(bars[0]["ts"]) != manifest.observed_range["start"]:
        raise ValueError("observed_range_start_mismatch")
    if str(bars[-1]["ts"]) != manifest.observed_range["end"]:
        raise ValueError("observed_range_end_mismatch")

    reloaded_df = pd.DataFrame(bars)
    reloaded_df["ts"] = pd.to_datetime(reloaded_df["ts"]).dt.date
    norm_df = normalize_ohlcv_to_signal_df(reloaded_df)
    recomputed_digest = dataset_digest(norm_df, manifest.ticker)
    if recomputed_digest != manifest.dataset_sha256:
        raise ValueError(
            f"dataset_digest_mismatch: manifest {manifest.dataset_sha256} != computed {recomputed_digest}"
        )

    # Re-read and verify review_csv representation
    csv_file = (root / Path(manifest.review_csv.path)).resolve()
    csv_df = pd.read_csv(csv_file)
    if len(csv_df) != manifest.row_count:
        raise ValueError(f"review_csv_row_count_mismatch: csv {len(csv_df)} != manifest {manifest.row_count}")

    norm_csv_df = normalize_ohlcv_to_signal_df(csv_df)
    if str(norm_csv_df["ts"].iloc[0]) != manifest.observed_range["start"]:
        raise ValueError("review_csv_observed_range_start_mismatch")
    if str(norm_csv_df["ts"].iloc[-1]) != manifest.observed_range["end"]:
        raise ValueError("review_csv_observed_range_end_mismatch")

    # Check that review_csv values match canonical dataset values within floating point precision
    for col in ("adj_close", "o", "c", "h", "l", "v"):
        orig_vals = norm_df[col].astype(float).values
        csv_vals = norm_csv_df[col].astype(float).values
        if not np.allclose(orig_vals, csv_vals, rtol=1e-5, atol=1e-5):
            raise ValueError(
                f"review_csv_dataset_mismatch: column '{col}' diverges from canonical dataset"
            )

    # Semantic cross-checks on evidence JSON files
    source_json = json.loads((root / Path(manifest.source.path)).read_text(encoding="utf-8"))
    if source_json.get("ticker_requested") != manifest.ticker:
        raise ValueError("source_ticker_mismatch")
    if source_json.get("vendor_symbol") != manifest.ticker:
        raise ValueError("source_vendor_symbol_mismatch")
    if source_json.get("provider") != manifest.source_provider:
        raise ValueError("source_provider_mismatch")
    if source_json.get("period") != manifest.period:
        raise ValueError("source_period_mismatch")
    if source_json.get("interval") != manifest.interval:
        raise ValueError("source_interval_mismatch")
    if source_json.get("row_count") != manifest.row_count:
        raise ValueError("source_row_count_mismatch")
    if source_json.get("first_observation") != manifest.observed_range["start"]:
        raise ValueError("source_first_observation_mismatch")
    if source_json.get("last_observation") != manifest.observed_range["end"]:
        raise ValueError("source_last_observation_mismatch")
    if source_json.get("dataset_sha256") != manifest.dataset_sha256:
        raise ValueError("source_digest_mismatch")
    if source_json.get("artifact_sha256") != manifest.dataset_artifact.sha256:
        raise ValueError("source_artifact_sha_mismatch")

    calendar_json = json.loads((root / Path(manifest.calendar.path)).read_text(encoding="utf-8"))
    if calendar_json.get("ticker") != manifest.ticker:
        raise ValueError("calendar_ticker_mismatch")
    if calendar_json.get("dataset_sha256") != manifest.dataset_sha256:
        raise ValueError("calendar_digest_mismatch")
    if calendar_json.get("first_date") != manifest.observed_range["start"]:
        raise ValueError("calendar_first_date_mismatch")
    if calendar_json.get("last_date") != manifest.observed_range["end"]:
        raise ValueError("calendar_last_date_mismatch")
    if calendar_json.get("total_trading_days") != manifest.row_count:
        raise ValueError("calendar_row_count_mismatch")

    adj_json = json.loads((root / Path(manifest.adjustments.path)).read_text(encoding="utf-8"))
    if adj_json.get("ticker") != manifest.ticker:
        raise ValueError("adjustments_ticker_mismatch")
    if adj_json.get("dataset_sha256") != manifest.dataset_sha256:
        raise ValueError("adjustments_digest_mismatch")

    pit_json = json.loads((root / Path(manifest.point_in_time.path)).read_text(encoding="utf-8"))
    if pit_json.get("ticker") != manifest.ticker:
        raise ValueError("point_in_time_ticker_mismatch")
    if pit_json.get("dataset_sha256") != manifest.dataset_sha256:
        raise ValueError("point_in_time_digest_mismatch")
    if pit_json.get("artifact_sha256") != manifest.dataset_artifact.sha256:
        raise ValueError("point_in_time_artifact_sha_mismatch")
    if pit_json.get("artifact_path") != manifest.dataset_artifact.path:
        raise ValueError("point_in_time_artifact_path_mismatch")
    if pit_json.get("collected_at_utc") != manifest.collected_at_utc:
        raise ValueError("point_in_time_collected_at_mismatch")

    return manifest


def approve_candidate(
    candidate_path: str | Path,
    reviewed_by: str,
    review_notes: str,
    confirm_digest: str,
    confirm_candidate_id: str,
    confirmation: str,
    registry_path: Optional[Path | str] = None,
    project_root: Optional[Path | str] = None,
    settings_path: Optional[Path | str] = None,
) -> Approval:
    """Explicit human approval mechanism.

    Validates candidate, requires non-empty human review metadata,
    requires confirmation='APPROVE_DATASET_FOR_PAPER_TRADING_ONLY',
    verifies exact 64-hex dataset digest AND candidate_id confirmation,
    checks duplicate prevention, and writes approval atomically into Registry.
    """
    root = (Path(project_root) if project_root else PROJECT_ROOT).resolve()
    reg_file = (Path(registry_path) if registry_path else REGISTRY).resolve()

    if confirmation != APPROVAL_CONFIRMATION_TOKEN:
        raise ValueError(
            f"invalid_confirmation_token: expected '{APPROVAL_CONFIRMATION_TOKEN}', got '{confirmation}'"
        )

    if not isinstance(reviewed_by, str) or not reviewed_by.strip():
        raise ValueError("reviewed_by_required: human reviewer name must be provided")

    if not isinstance(review_notes, str) or not review_notes.strip():
        raise ValueError("review_notes_required: non-empty review notes are required")

    if not isinstance(confirm_digest, str) or len(confirm_digest.strip()) != 64:
        raise ValueError("confirm_digest_required: exact 64-hex dataset digest required")

    if not isinstance(confirm_candidate_id, str) or len(confirm_candidate_id.strip()) != 64:
        raise ValueError("confirm_candidate_id_required: exact 64-hex candidate ID required")

    # Validate candidate bundle first
    manifest = validate_candidate(candidate_path, project_root=root, settings_path=settings_path)

    # Confirm digest exact match
    if confirm_digest.strip().lower() != manifest.dataset_sha256.lower():
        raise ValueError(
            f"confirm_digest_mismatch: expected {manifest.dataset_sha256}, got {confirm_digest}"
        )

    # Confirm candidate_id exact match
    if confirm_candidate_id.strip().lower() != manifest.candidate_id.lower():
        raise ValueError(
            f"confirm_candidate_id_mismatch: expected {manifest.candidate_id}, got {confirm_candidate_id}"
        )

    # Print both confirmed identities before registry mutation
    print(f"CONFIRMED_DATASET_DIGEST: {manifest.dataset_sha256}")
    print(f"CONFIRMED_CANDIDATE_ID:   {manifest.candidate_id}")

    # Load registry
    if not reg_file.is_file():
        reg = Registry(version=1, approvals=[])
    else:
        reg = Registry.model_validate_json(reg_file.read_bytes())

    # Duplicate check: fail closed on duplicate digest
    if any(a.dataset_sha256 == manifest.dataset_sha256 for a in reg.approvals):
        raise ValueError(f"duplicate_approval: dataset {manifest.dataset_sha256} is already approved")

    new_approval = Approval(
        candidate_id=manifest.candidate_id,
        ticker=manifest.ticker,
        strategy_id=manifest.strategy_id,
        intended_use=manifest.intended_use,
        dataset_sha256=manifest.dataset_sha256,
        collected_at_utc=manifest.collected_at_utc,
        dataset_artifact=manifest.dataset_artifact,
        review_csv=manifest.review_csv,
        source=manifest.source,
        calendar=manifest.calendar,
        adjustments=manifest.adjustments,
        point_in_time=manifest.point_in_time,
        reviewed_by=reviewed_by.strip(),
        review_notes=review_notes.strip(),
        status="approved",
    )

    # Display approval summary
    print("\n--- APPROVAL SUMMARY ---")
    print(f"Ticker:          {manifest.ticker}")
    print(f"Dataset SHA-256: {manifest.dataset_sha256}")
    print(f"Candidate ID:    {manifest.candidate_id}")
    print(f"Reviewed By:     {reviewed_by.strip()}")
    print(f"Review Notes:    {review_notes.strip()}")
    print(f"Canonical JSON:  {manifest.dataset_artifact.path}")
    print(f"Review CSV:      {manifest.review_csv.path}")
    print("------------------------\n")

    # Append and atomic write
    reg.approvals.append(new_approval)
    save_registry(reg, registry_path=reg_file)

    # Re-verify written registry
    re_read = Registry.model_validate_json(reg_file.read_bytes())
    if not any(a.dataset_sha256 == manifest.dataset_sha256 for a in re_read.approvals):
        raise RuntimeError("registry_write_verification_failed")

    return new_approval


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Meridian Paper Data Approval Candidate & Governance Gate"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: build
    build_parser = subparsers.add_parser("build", help="Build a new candidate evidence bundle")
    build_parser.add_argument("--ticker", required=True, help="Ticker symbol (e.g. PETR4.SA)")
    build_parser.add_argument("--period", default="2y", help="Historical period (default: 2y)")
    build_parser.add_argument("--interval", default="1d", help="Candle interval (default: 1d)")
    build_parser.add_argument("--output-dir", default=None, help="Custom output directory")
    build_parser.add_argument("--strategy-id", default=None, help="Strategy ID (defaults to active strategy)")
    build_parser.add_argument("--settings", default=None, help="Custom settings.yaml path")

    # Subcommand: validate
    val_parser = subparsers.add_parser("validate", help="Validate an existing candidate evidence bundle")
    val_parser.add_argument("--candidate", required=True, help="Path to candidate_manifest.json")
    val_parser.add_argument("--settings", default=None, help="Custom settings.yaml path")

    # Subcommand: approve (DO NOT run during NEXUS-003-R1)
    app_parser = subparsers.add_parser("approve", help="Explicit human approval of a candidate bundle")
    app_parser.add_argument("--candidate", required=True, help="Path to candidate_manifest.json")
    app_parser.add_argument("--reviewed-by", required=True, help="Human reviewer name")
    app_parser.add_argument("--review-notes", required=True, help="Detailed review notes")
    app_parser.add_argument("--confirm-digest", required=True, help="Exact 64-hex dataset digest")
    app_parser.add_argument("--confirm-candidate-id", required=True, help="Exact 64-hex candidate ID")
    app_parser.add_argument(
        "--confirmation",
        required=True,
        help=f"Must equal '{APPROVAL_CONFIRMATION_TOKEN}'",
    )
    app_parser.add_argument("--registry", default=None, help="Custom registry path")
    app_parser.add_argument("--settings", default=None, help="Custom settings.yaml path")

    args = parser.parse_args(argv)

    try:
        if args.command == "build":
            manifest = build_candidate_bundle(
                ticker=args.ticker,
                period=args.period,
                interval=args.interval,
                output_dir=Path(args.output_dir) if args.output_dir else None,
                strategy_id=args.strategy_id,
                settings_path=Path(args.settings) if args.settings else None,
            )
            print(
                f"CANDIDATE_BUILD_SUCCESS: ticker={manifest.ticker} "
                f"candidate_id={manifest.candidate_id} digest={manifest.dataset_sha256}"
            )
            return 0

        elif args.command == "validate":
            manifest = validate_candidate(
                args.candidate,
                settings_path=Path(args.settings) if args.settings else None,
            )
            print(
                f"CANDIDATE_VALIDATION_PASS: ticker={manifest.ticker} "
                f"candidate_id={manifest.candidate_id} digest={manifest.dataset_sha256}"
            )
            return 0

        elif args.command == "approve":
            approval = approve_candidate(
                candidate_path=args.candidate,
                reviewed_by=args.reviewed_by,
                review_notes=args.review_notes,
                confirm_digest=args.confirm_digest,
                confirm_candidate_id=args.confirm_candidate_id,
                confirmation=args.confirmation,
                registry_path=Path(args.registry) if args.registry else None,
                settings_path=Path(args.settings) if args.settings else None,
            )
            print(f"APPROVAL_RECORDED_SUCCESS: digest={approval.dataset_sha256} reviewer={approval.reviewed_by}")
            return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
