"""Approval Candidate Builder & Governance Gate (NEXUS-003).

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

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from backend.app.markets import resolve_market
from trading_bot.data.approval import (
    PROJECT_ROOT,
    REGISTRY,
    Approval,
    Evidence,
    Registry,
    dataset_digest,
    normalize_ohlcv_to_signal_df,
    save_registry,
)
from trading_bot.data.signal_input import SignalBar

try:
    import yfinance as yf
    _YF_VERSION = getattr(yf, "__version__", "unknown")
except Exception:
    _YF_VERSION = "unavailable"


class CandidateManifest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    candidate_version: Literal[1] = 1
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
    strategy_id: str = "donchian_breakout_v4",
    project_root: Optional[Path] = None,
    df: Optional[pd.DataFrame] = None,
) -> CandidateManifest:
    """Obtain dataset via production path, normalize into eng_df, and build evidence bundle.

    NEVER modifies config/data_approvals.json.
    NEVER marks anything approved automatically.
    """
    root = (project_root or PROJECT_ROOT).resolve()
    collected_at = datetime.now(timezone.utc).isoformat()

    # 1. Obtain market data via exact production path unless pre-supplied
    if df is None:
        market = resolve_market(ticker)
        df = market.fetch_ohlcv(ticker, period=period, interval=interval)

    if df is None or len(df) < 201:
        count = len(df) if df is not None else 0
        raise ValueError(f"insufficient_ohlcv_data: got {count} bars, minimum 201 required")

    # 2. Extract deterministic signal dataframe using shared helper
    eng_df = normalize_ohlcv_to_signal_df(df)

    # 3. Calculate canonical dataset digest
    d_sha = dataset_digest(eng_df, ticker)

    # 4. Prepare candidate directory
    safe_ticker = ticker.replace("^", "").replace(".", "_").replace("/", "_")
    if output_dir is not None:
        bundle_dir = Path(output_dir).resolve()
    else:
        bundle_dir = (root / "data" / "approval_candidates" / f"{safe_ticker}_{d_sha[:16]}").resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # 5. Dataset artifact (canonical JSON payload and tabular CSV)
    dataset_artifact_file = bundle_dir / "dataset.json"
    bars = [
        SignalBar.model_validate(row).model_dump(mode="json")
        for row in eng_df[list(SignalBar.model_fields)].to_dict("records")
    ]
    payload_dict = {"ticker": ticker, "bars": bars}
    dataset_artifact_file.write_text(
        json.dumps(payload_dict, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
    artifact_bytes = dataset_artifact_file.read_bytes()
    artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()
    dataset_artifact_ev = Evidence(
        path=_rel_path_str(dataset_artifact_file, root),
        sha256=artifact_sha,
    )

    # Also export tabular dataset.csv for spreadsheet inspection
    eng_df.to_csv(bundle_dir / "dataset.csv", index=False)

    first_obs = str(eng_df["ts"].iloc[0])
    last_obs = str(eng_df["ts"].iloc[-1])
    row_count = len(eng_df)

    # 6. Source evidence (Honest yfinance provenance)
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
        "artifact_sha256": artifact_sha,
        "feed_type": "vendor_daily_bars",
        "official_exchange_feed": False,
        "disclaimer": (
            "Not official B3 tick/quote data, exchange tick, or NBBO. "
            "Sourced from yfinance historical daily bars."
        ),
    }
    source_file = bundle_dir / "source.json"
    source_file.write_text(json.dumps(source_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    source_ev = Evidence(
        path=_rel_path_str(source_file, root),
        sha256=hashlib.sha256(source_file.read_bytes()).hexdigest(),
    )

    # 7. Calendar evidence
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
    calendar_file = bundle_dir / "calendar.json"
    calendar_file.write_text(json.dumps(calendar_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    calendar_ev = Evidence(
        path=_rel_path_str(calendar_file, root),
        sha256=hashlib.sha256(calendar_file.read_bytes()).hexdigest(),
    )

    # 8. Adjustments evidence
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
    adjustments_file = bundle_dir / "adjustments.json"
    adjustments_file.write_text(json.dumps(adjustments_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    adjustments_ev = Evidence(
        path=_rel_path_str(adjustments_file, root),
        sha256=hashlib.sha256(adjustments_file.read_bytes()).hexdigest(),
    )

    # 9. Point-in-time evidence
    pit_payload = {
        "ticker": ticker,
        "evidence_type": "capture_time_evidence",
        "collected_at_utc": collected_at,
        "dataset_sha256": d_sha,
        "artifact_path": _rel_path_str(dataset_artifact_file, root),
        "artifact_sha256": artifact_sha,
        "historical_point_in_time_guarantee": False,
        "disclaimer": (
            "Capture-time snapshot only. Sourced at collected_at_utc. "
            "No point-in-time guarantee against post-hoc revisions, delistings, "
            "or corporate restatements by yfinance."
        ),
    }
    pit_file = bundle_dir / "point_in_time.json"
    pit_file.write_text(json.dumps(pit_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pit_ev = Evidence(
        path=_rel_path_str(pit_file, root),
        sha256=hashlib.sha256(pit_file.read_bytes()).hexdigest(),
    )

    # 10. Manifest
    limitations = [
        "Provider data is yfinance, not official B3 tick/quote feed",
        "Adjustments provided by vendor without independent audit",
        "Capture-time snapshot without historical restatement protection",
    ]
    manifest = CandidateManifest(
        candidate_version=1,
        ticker=ticker,
        dataset_sha256=d_sha,
        strategy_id=strategy_id,
        source_provider="yfinance",
        period=period,
        interval=interval,
        observed_range={"start": first_obs, "end": last_obs},
        collected_at_utc=collected_at,
        row_count=row_count,
        dataset_artifact=dataset_artifact_ev,
        source=source_ev,
        calendar=calendar_ev,
        adjustments=adjustments_ev,
        point_in_time=pit_ev,
        limitations=limitations,
        intended_use="PAPER_TRADING",
    )

    manifest_file = bundle_dir / "candidate_manifest.json"
    manifest_file.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")

    # 11. Self-validate immediately to guarantee bundle consistency
    validate_candidate(manifest_file, project_root=root)

    return manifest


def validate_candidate(
    candidate_path: str | Path,
    project_root: Optional[Path] = None,
) -> CandidateManifest:
    """Deterministic validator for candidate evidence bundles.

    Recomputes dataset_sha256 and every evidence file hash.
    Rejects missing files, changed files, path traversal/outside-project paths,
    ticker mismatch, altered dataset, or conflicting identity.
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

    # Check each evidence path
    evidence_map = {
        "dataset_artifact": manifest.dataset_artifact,
        "source": manifest.source,
        "calendar": manifest.calendar,
        "adjustments": manifest.adjustments,
        "point_in_time": manifest.point_in_time,
    }

    for ev_name, ev in evidence_map.items():
        rel_path = Path(ev.path)
        if rel_path.is_absolute():
            raise ValueError(f"absolute_evidence_path: {ev_name} has {ev.path}")

        # Check for path traversal components (e.g. '../')
        if any(part == ".." for part in rel_path.parts):
            raise ValueError(f"path_traversal_forbidden: {ev_name} has {ev.path}")

        file_path = (root / rel_path).resolve()
        if not file_path.is_relative_to(root):
            raise ValueError(f"evidence_outside_project: {ev_name} points to {file_path}")

        if not file_path.is_file():
            raise ValueError(f"missing_evidence_file: {ev_name} file not found: {file_path}")

        # Recompute file sha256
        actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if actual_hash != ev.sha256:
            raise ValueError(f"evidence_hash_mismatch: {ev_name} expected {ev.sha256}, got {actual_hash}")

    # Re-read and recompute dataset_sha256
    ds_file = (root / Path(manifest.dataset_artifact.path)).resolve()
    if ds_file.suffix == ".json":
        raw_obj = json.loads(ds_file.read_text(encoding="utf-8"))
        if isinstance(raw_obj, dict) and "bars" in raw_obj:
            reloaded_df = pd.DataFrame(raw_obj["bars"])
        elif isinstance(raw_obj, list):
            reloaded_df = pd.DataFrame(raw_obj)
        else:
            raise ValueError("invalid_dataset_json_format")
    else:
        reloaded_df = pd.read_csv(ds_file)

    reloaded_df["ts"] = pd.to_datetime(reloaded_df["ts"]).dt.date
    norm_df = normalize_ohlcv_to_signal_df(reloaded_df)
    recomputed_digest = dataset_digest(norm_df, manifest.ticker)
    if recomputed_digest != manifest.dataset_sha256:
        raise ValueError(
            f"dataset_digest_mismatch: manifest {manifest.dataset_sha256} != computed {recomputed_digest}"
        )

    # Semantic cross-checks
    source_json = json.loads((root / Path(manifest.source.path)).read_text(encoding="utf-8"))
    if source_json.get("ticker_requested") != manifest.ticker:
        raise ValueError("source_ticker_mismatch")
    if source_json.get("dataset_sha256") != manifest.dataset_sha256:
        raise ValueError("source_digest_mismatch")
    if source_json.get("artifact_sha256") != manifest.dataset_artifact.sha256:
        raise ValueError("source_artifact_sha_mismatch")

    calendar_json = json.loads((root / Path(manifest.calendar.path)).read_text(encoding="utf-8"))
    if calendar_json.get("dataset_sha256") != manifest.dataset_sha256:
        raise ValueError("calendar_digest_mismatch")
    if calendar_json.get("total_trading_days") != manifest.row_count:
        raise ValueError("calendar_row_count_mismatch")

    adj_json = json.loads((root / Path(manifest.adjustments.path)).read_text(encoding="utf-8"))
    if adj_json.get("dataset_sha256") != manifest.dataset_sha256:
        raise ValueError("adjustments_digest_mismatch")

    pit_json = json.loads((root / Path(manifest.point_in_time.path)).read_text(encoding="utf-8"))
    if pit_json.get("dataset_sha256") != manifest.dataset_sha256:
        raise ValueError("point_in_time_digest_mismatch")
    if pit_json.get("artifact_sha256") != manifest.dataset_artifact.sha256:
        raise ValueError("point_in_time_artifact_sha_mismatch")

    return manifest


def approve_candidate(
    candidate_path: str | Path,
    reviewed_by: str,
    review_notes: str,
    confirm_digest: str,
    registry_path: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> Approval:
    """Explicit human approval mechanism.

    Validates candidate, requires non-empty human review metadata,
    verifies exact 64-hex digest confirmation, checks duplicate prevention,
    and writes approval atomically into Registry.
    """
    root = (project_root or PROJECT_ROOT).resolve()
    reg_file = (registry_path or REGISTRY).resolve()

    if not isinstance(reviewed_by, str) or not reviewed_by.strip():
        raise ValueError("reviewed_by_required: human reviewer name must be provided")

    if not isinstance(review_notes, str) or not review_notes.strip():
        raise ValueError("review_notes_required: non-empty review notes are required")

    # Validate candidate bundle first
    manifest = validate_candidate(candidate_path, project_root=root)

    # Confirm digest exact match
    if not isinstance(confirm_digest, str) or confirm_digest.strip() != manifest.dataset_sha256:
        raise ValueError(
            f"confirm_digest_mismatch: expected {manifest.dataset_sha256}, got {confirm_digest}"
        )

    # Load registry
    if not reg_file.is_file():
        reg = Registry(version=1, approvals=[])
    else:
        reg = Registry.model_validate_json(reg_file.read_bytes())

    # Duplicate check: fail closed on duplicate
    if any(a.dataset_sha256 == manifest.dataset_sha256 for a in reg.approvals):
        raise ValueError(f"duplicate_approval: dataset {manifest.dataset_sha256} is already approved")

    new_approval = Approval(
        dataset_sha256=manifest.dataset_sha256,
        reviewed_by=reviewed_by.strip(),
        review_notes=review_notes.strip(),
        status="approved",
        source=manifest.source,
        calendar=manifest.calendar,
        adjustments=manifest.adjustments,
        point_in_time=manifest.point_in_time,
    )

    # Display what will be approved before mutating registry
    print("\n--- APPROVAL SUMMARY ---")
    print(f"Ticker:          {manifest.ticker}")
    print(f"Dataset SHA-256: {manifest.dataset_sha256}")
    print(f"Reviewed By:     {reviewed_by.strip()}")
    print(f"Review Notes:    {review_notes.strip()}")
    print(f"Source Evidence: {manifest.source.path} ({manifest.source.sha256[:12]}...)")
    print(f"Calendar:        {manifest.calendar.path} ({manifest.calendar.sha256[:12]}...)")
    print(f"Adjustments:     {manifest.adjustments.path} ({manifest.adjustments.sha256[:12]}...)")
    print(f"Point-In-Time:   {manifest.point_in_time.path} ({manifest.point_in_time.sha256[:12]}...)")
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
    build_parser.add_argument("--strategy-id", default="donchian_breakout_v4", help="Strategy ID")

    # Subcommand: validate
    val_parser = subparsers.add_parser("validate", help="Validate an existing candidate evidence bundle")
    val_parser.add_argument("--candidate", required=True, help="Path to candidate_manifest.json")

    # Subcommand: approve (DO NOT run during NEXUS-003)
    app_parser = subparsers.add_parser("approve", help="Explicit human approval of a candidate bundle")
    app_parser.add_argument("--candidate", required=True, help="Path to candidate_manifest.json")
    app_parser.add_argument("--reviewed-by", required=True, help="Human reviewer name")
    app_parser.add_argument("--review-notes", required=True, help="Detailed review notes")
    app_parser.add_argument("--confirm-digest", required=True, help="Exact 64-hex dataset digest")
    app_parser.add_argument("--registry", default=None, help="Custom registry path")

    args = parser.parse_args(argv)

    try:
        if args.command == "build":
            manifest = build_candidate_bundle(
                ticker=args.ticker,
                period=args.period,
                interval=args.interval,
                output_dir=Path(args.output_dir) if args.output_dir else None,
                strategy_id=args.strategy_id,
            )
            print(f"CANDIDATE_BUILD_SUCCESS: ticker={manifest.ticker} digest={manifest.dataset_sha256}")
            return 0

        elif args.command == "validate":
            manifest = validate_candidate(args.candidate)
            print(f"CANDIDATE_VALIDATION_PASS: ticker={manifest.ticker} digest={manifest.dataset_sha256}")
            return 0

        elif args.command == "approve":
            approval = approve_candidate(
                candidate_path=args.candidate,
                reviewed_by=args.reviewed_by,
                review_notes=args.review_notes,
                confirm_digest=args.confirm_digest,
                registry_path=Path(args.registry) if args.registry else None,
            )
            print(f"APPROVAL_RECORDED_SUCCESS: digest={approval.dataset_sha256} reviewer={approval.reviewed_by}")
            return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
