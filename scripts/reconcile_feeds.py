#!/usr/bin/env python3
"""Deterministic Multi-Source Market Data Reconciliation Pipeline CLI.

Compares market data observations across distinct sources (e.g. B3 COTAHIST
daily files vs historical bar feeds / SQLite database observations).
Converts raw feeds into validated ObservationRecord series, invokes
DataReconciliationAgent.reconcile, computes exact residuals cent-by-cent,
matches corporate actions strictly with SHA-256 hashes, logs UNEXPLAINED_MISMATCH
and MISSING_DATA, and emits deterministic reconciliation report artifacts
backed by SHA-256 digests.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import sys
from typing import Any, Literal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading_bot.data.data_reconciliation import (
    DataReconciliationAgent,
    EventDocument,
    ObservationRecord,
    ReconciliationReport,
)

logger = logging.getLogger("reconcile_feeds")


def compute_file_sha256(path: Path | str) -> str:
    """Compute deterministic SHA-256 digest of a file."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"file_not_found: {p}")
    hasher = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def detect_source_type(path: Path | str) -> str:
    """Detect source type based on file path properties."""
    p = Path(path)
    if p.is_dir():
        if (p / "quotes.csv").is_file() and (p / "manifest.json").is_file():
            return "cotahist"
        return "dir"
    name = p.name.lower()
    if name.endswith(".db") or name.endswith(".sqlite") or name.endswith(".sqlite3"):
        return "sqlite"
    if name.endswith(".csv"):
        return "csv"
    if name.endswith(".json"):
        return "json"
    if "cotahist" in name or name.endswith(".txt"):
        return "cotahist"
    return "csv"


def load_from_cotahist(
    path: Path | str,
    ticker: str,
    unit: str = "BRL/share",
) -> list[ObservationRecord]:
    """Load ObservationRecords for a given ticker from COTAHIST exports or raw files."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"cotahist_path_not_found: {p}")

    # Case 1: Directory exported by cotahist.export_research
    if p.is_dir():
        csv_file = p / "quotes.csv"
        manifest_file = p / "manifest.json"
        if not csv_file.is_file() or not manifest_file.is_file():
            raise ValueError(f"invalid_cotahist_export_dir: missing quotes.csv or manifest.json in {p}")
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        source_sha = manifest.get("source_sha256", compute_file_sha256(csv_file))
        source_ref = f"cotahist:{manifest_file.parent.name}"
        records: list[ObservationRecord] = []
        with csv_file.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("ticker", "").strip() != ticker:
                    continue
                records.append(
                    ObservationRecord(
                        ticker=ticker,
                        date=str(row["trading_date"]).strip(),
                        price=float(row["close"]),
                        volume=float(row["financial_volume"]) if row.get("financial_volume") else None,
                        unit=unit,
                        source_ref=source_ref,
                        source_sha256=source_sha,
                    )
                )
        return sorted(records, key=lambda r: r.date)

    # Case 2: File is a CSV
    if p.name.lower().endswith(".csv"):
        manifest_file = p.parent / "manifest.json"
        if manifest_file.is_file():
            try:
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                source_sha = manifest.get("source_sha256", compute_file_sha256(p))
            except Exception:
                source_sha = compute_file_sha256(p)
        else:
            source_sha = compute_file_sha256(p)
        source_ref = f"cotahist:{p.name}"
        records = []
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row_ticker = (row.get("ticker") or row.get("symbol") or "").strip()
                if row_ticker and row_ticker != ticker:
                    continue
                date_val = str(row.get("trading_date") or row.get("date") or row.get("ts")).strip()
                price_val = float(row.get("close") or row.get("c") or row.get("price"))
                vol_val = None
                for vk in ("financial_volume", "volume", "v"):
                    if vk in row and row[vk]:
                        vol_val = float(row[vk])
                        break
                records.append(
                    ObservationRecord(
                        ticker=ticker,
                        date=date_val,
                        price=price_val,
                        volume=vol_val,
                        unit=unit,
                        source_ref=source_ref,
                        source_sha256=source_sha,
                    )
                )
        return sorted(records, key=lambda r: r.date)

    # Case 3: Raw fixed-width COTAHIST file (245 bytes)
    file_sha = compute_file_sha256(p)
    from trading_bot.data.cotahist import read_file

    quotes, _, _, _ = read_file(p, {ticker})
    records = []
    for q, _ in quotes:
        if q.ticker == ticker:
            records.append(
                ObservationRecord(
                    ticker=ticker,
                    date=q.trading_date.isoformat(),
                    price=float(q.close),
                    volume=float(q.financial_volume),
                    unit=unit,
                    source_ref=f"cotahist_raw:{p.name}",
                    source_sha256=file_sha,
                )
            )
    return sorted(records, key=lambda r: r.date)


def load_from_sqlite(
    db_path: Path | str,
    ticker: str,
    price_col: str = "c",
    unit: str = "BRL/share",
) -> list[ObservationRecord]:
    """Load ObservationRecords from SQLite database ohlcv table."""
    p = Path(db_path)
    if not p.is_file():
        raise FileNotFoundError(f"sqlite_db_not_found: {p}")

    db_sha = compute_file_sha256(p)
    source_ref = f"sqlite:{p.name}"

    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    try:
        # Check if table ohlcv exists
        table_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ohlcv'"
        ).fetchone()
        if not table_check:
            raise ValueError(f"table_ohlcv_not_found_in_{p}")

        query = f"SELECT ticker, ts, o, h, l, {price_col} AS close_val, v FROM ohlcv WHERE ticker = ? ORDER BY ts ASC"
        cursor = conn.execute(query, [ticker])
        rows = cursor.fetchall()
        records: list[ObservationRecord] = []
        for row in rows:
            ts_str = str(row["ts"]).split(" ")[0].strip()
            records.append(
                ObservationRecord(
                    ticker=ticker,
                    date=ts_str,
                    price=float(row["close_val"]),
                    volume=float(row["v"]) if row["v"] is not None else None,
                    unit=unit,
                    source_ref=source_ref,
                    source_sha256=db_sha,
                )
            )
        return records
    finally:
        conn.close()


def load_from_csv(
    csv_path: Path | str,
    ticker: str,
    unit: str = "BRL/share",
) -> list[ObservationRecord]:
    """Load ObservationRecords from a generic bar feed CSV file."""
    p = Path(csv_path)
    if not p.is_file():
        raise FileNotFoundError(f"csv_not_found: {p}")

    file_sha = compute_file_sha256(p)
    source_ref = f"csv:{p.name}"

    records: list[ObservationRecord] = []
    with p.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_ticker = (row.get("ticker") or row.get("symbol") or "").strip()
            if row_ticker and row_ticker != ticker:
                continue

            date_val = str(row.get("date") or row.get("ts") or row.get("trading_date") or "").strip()
            if not date_val:
                continue
            date_val = date_val.split(" ")[0].split("T")[0]

            price_val: float | None = None
            for pk in ("close", "c", "price", "adj_close"):
                if pk in row and row[pk] is not None and row[pk] != "":
                    price_val = float(row[pk])
                    break
            if price_val is None:
                continue

            vol_val = None
            for vk in ("volume", "v", "financial_volume"):
                if vk in row and row[vk] is not None and row[vk] != "":
                    vol_val = float(row[vk])
                    break

            records.append(
                ObservationRecord(
                    ticker=ticker,
                    date=date_val,
                    price=price_val,
                    volume=vol_val,
                    unit=unit,
                    source_ref=source_ref,
                    source_sha256=file_sha,
                )
            )
    return sorted(records, key=lambda r: r.date)


def load_from_json(
    json_path: Path | str,
    ticker: str,
    unit: str = "BRL/share",
) -> list[ObservationRecord]:
    """Load ObservationRecords from JSON file."""
    p = Path(json_path)
    if not p.is_file():
        raise FileNotFoundError(f"json_not_found: {p}")

    file_sha = compute_file_sha256(p)
    source_ref = f"json:{p.name}"

    content = json.loads(p.read_text(encoding="utf-8"))
    raw_list: list[dict[str, Any]]
    if isinstance(content, list):
        raw_list = content
    elif isinstance(content, dict) and "records" in content:
        raw_list = content["records"]
    elif isinstance(content, dict) and "bars" in content:
        raw_list = content["bars"]
    else:
        raise ValueError(f"unsupported_json_structure_in_{p}")

    records: list[ObservationRecord] = []
    for item in raw_list:
        item_ticker = item.get("ticker", ticker)
        if item_ticker != ticker:
            continue
        date_str = str(item.get("date") or item.get("ts") or item.get("trading_date")).split(" ")[0].split("T")[0]
        price_val = float(item.get("price") or item.get("close") or item.get("c"))
        vol_val = float(item["volume"]) if "volume" in item and item["volume"] is not None else None
        item_unit = item.get("unit", unit)
        item_ref = item.get("source_ref", source_ref)
        item_sha = item.get("source_sha256", file_sha)

        records.append(
            ObservationRecord(
                ticker=ticker,
                date=date_str,
                price=price_val,
                volume=vol_val,
                unit=item_unit,
                source_ref=item_ref,
                source_sha256=item_sha,
            )
        )
    return sorted(records, key=lambda r: r.date)


def load_observations(
    source_path: Path | str,
    source_type: str | None,
    ticker: str,
    unit: str = "BRL/share",
) -> list[ObservationRecord]:
    """Dispatch loading to appropriate loader based on type."""
    stype = (source_type or detect_source_type(source_path)).lower()
    if stype in ("cotahist", "cotahist_raw", "cotahist_csv"):
        return load_from_cotahist(source_path, ticker=ticker, unit=unit)
    if stype in ("sqlite", "db"):
        return load_from_sqlite(source_path, ticker=ticker, unit=unit)
    if stype == "csv":
        return load_from_csv(source_path, ticker=ticker, unit=unit)
    if stype == "json":
        return load_from_json(source_path, ticker=ticker, unit=unit)
    raise ValueError(f"unrecognized_source_type: {stype} for {source_path}")


def load_events_file(events_path: Path | str) -> list[EventDocument]:
    """Load documented corporate events from a JSON file."""
    p = Path(events_path)
    if not p.is_file():
        raise FileNotFoundError(f"events_file_not_found: {p}")

    data = json.loads(p.read_text(encoding="utf-8"))
    raw_list: list[dict[str, Any]]
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict) and "events" in data:
        raw_list = data["events"]
    else:
        raise ValueError(f"invalid_events_json_structure_in_{p}")

    events: list[EventDocument] = []
    for item in raw_list:
        events.append(EventDocument.model_validate(item))
    return events


def reconcile_feeds(
    series_a: list[ObservationRecord],
    series_b: list[ObservationRecord],
    events: list[EventDocument] | None = None,
    tolerance: float = 0.0001,
) -> ReconciliationReport:
    """Run deterministic reconciliation between two observation series."""
    agent = DataReconciliationAgent(tolerance=tolerance)
    return agent.reconcile(series_a, series_b, events=events)


def export_reconciliation_report(
    report: ReconciliationReport,
    output_path: Path | str,
) -> dict[str, Any]:
    """Export reconciliation report to a deterministic JSON artifact with SHA-256."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    report_dict = report.model_dump(mode="json")
    json_bytes = json.dumps(
        report_dict,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")

    digest = hashlib.sha256(json_bytes).hexdigest()
    out.write_bytes(json_bytes)

    # Re-verify written file digest
    written_digest = compute_file_sha256(out)
    if written_digest != digest:
        raise IOError("reconciliation_report_integrity_verification_failed")

    return {
        "status": report.status,
        "ticker": report.ticker,
        "report_path": str(out.resolve()),
        "report_sha256": digest,
        "total_dates": report.total_dates,
        "exact_matches": report.exact_matches,
        "documented_matches": report.documented_matches,
        "unexplained_mismatches": report.unexplained_mismatches,
        "missing_data_count": report.missing_data_count,
        "max_absolute_residual": report.max_absolute_residual,
    }


def run_pipeline(
    source_a: str | Path,
    source_b: str | Path,
    ticker: str,
    source_a_type: str | None = None,
    source_b_type: str | None = None,
    events_path: str | Path | None = None,
    tolerance: float = 0.0001,
    output_path: str | Path | None = None,
    unit: str = "BRL/share",
) -> tuple[ReconciliationReport, dict[str, Any]]:
    """Execute complete feed reconciliation pipeline."""
    logger.info("Loading Source A observations from: %s", source_a)
    series_a = load_observations(source_a, source_a_type, ticker, unit=unit)
    logger.info("Loaded %d observations for %s from Source A", len(series_a), ticker)

    logger.info("Loading Source B observations from: %s", source_b)
    series_b = load_observations(source_b, source_b_type, ticker, unit=unit)
    logger.info("Loaded %d observations for %s from Source B", len(series_b), ticker)

    events: list[EventDocument] = []
    if events_path:
        logger.info("Loading documented corporate events from: %s", events_path)
        events = load_events_file(events_path)
        logger.info("Loaded %d corporate events", len(events))

    logger.info("Running DataReconciliationAgent (tolerance=%s)...", tolerance)
    report = reconcile_feeds(series_a, series_b, events=events, tolerance=tolerance)

    # Audit and log each discrepancy
    for item in report.items:
        if item.status == "UNEXPLAINED_MISMATCH":
            logger.warning(
                "[UNEXPLAINED_MISMATCH] date=%s ticker=%s price_a=%s price_b=%s delta=%s residual=%s reason=%s",
                item.date,
                item.ticker,
                item.price_a,
                item.price_b,
                item.price_delta,
                item.residual_delta,
                item.reason,
            )
        elif item.status == "MISSING_DATA":
            logger.warning(
                "[MISSING_DATA] date=%s ticker=%s price_a=%s price_b=%s reason=%s",
                item.date,
                item.ticker,
                item.price_a,
                item.price_b,
                item.reason,
            )

    if not output_path:
        output_path = Path("reports") / f"reconciliation_{ticker}_{report.status.lower()}.json"

    export_meta = export_reconciliation_report(report, output_path)
    logger.info(
        "Reconciliation report generated: status=%s path=%s sha256=%s",
        report.status,
        export_meta["report_path"],
        export_meta["report_sha256"],
    )
    return report, export_meta


def main(args: list[str] | None = None) -> int:
    """CLI entrypoint for feed reconciliation."""
    parser = argparse.ArgumentParser(
        description="Deterministic Multi-Source Market Data Reconciliation Pipeline",
    )
    parser.add_argument("--ticker", required=True, help="Stock ticker to reconcile (e.g. PETR4)")
    parser.add_argument("--source-a", required=True, help="Path to Source A (COTAHIST, SQLite, CSV, or JSON)")
    parser.add_argument(
        "--source-a-type",
        choices=["cotahist", "cotahist_raw", "cotahist_csv", "sqlite", "csv", "json"],
        default=None,
        help="Explicit Source A type (auto-detected if omitted)",
    )
    parser.add_argument("--source-b", required=True, help="Path to Source B (COTAHIST, SQLite, CSV, or JSON)")
    parser.add_argument(
        "--source-b-type",
        choices=["cotahist", "cotahist_raw", "cotahist_csv", "sqlite", "csv", "json"],
        default=None,
        help="Explicit Source B type (auto-detected if omitted)",
    )
    parser.add_argument("--events", default=None, help="Optional path to documented corporate actions JSON")
    parser.add_argument("--tolerance", type=float, default=0.0001, help="Tolerance for residual price deltas")
    parser.add_argument("--output", default=None, help="Output path for reconciliation report artifact JSON")
    parser.add_argument("--unit", default="BRL/share", help="Unit of asset prices (default: BRL/share)")
    parser.add_argument(
        "--allow-discrepancies",
        action="store_true",
        help="Exit with 0 even if discrepancies are detected",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    parsed = parser.parse_args(args)

    logging.basicConfig(
        level=logging.DEBUG if parsed.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        report, meta = run_pipeline(
            source_a=parsed.source_a,
            source_b=parsed.source_b,
            ticker=parsed.ticker,
            source_a_type=parsed.source_a_type,
            source_b_type=parsed.source_b_type,
            events_path=parsed.events,
            tolerance=parsed.tolerance,
            output_path=parsed.output,
            unit=parsed.unit,
        )
        print(json.dumps(meta, indent=2))
        if report.status == "RECONCILED" or parsed.allow_discrepancies:
            return 0
        return 1
    except Exception as exc:
        logger.error("Pipeline failed with error: %s", exc, exc_info=True)
        print(json.dumps({"status": "FAILED", "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
