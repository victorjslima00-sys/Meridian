"""Deterministic, immutable valuation snapshots.

Freezes active positions, balances, feed quotes, units and timestamps into
durable local snapshots. Fails closed immediately if any market quote is missing,
never falling back to entry_price.

Adheres strictly to NEXUS-001 evidence integrity contract:
- EvidencedQuote enforces recoverable evidence hashes and vendor semantics.
- Active positions bound strictly by trade_id (preventing ticker-only inheritance).
- Immutable persistence across filesystem JSON and SQLite rows with tamper detection.
- Cross-store crash window safety (partial write detection, no silent fallback).
- Exact-content retry can repair missing storage side; conflicts raise SnapshotIntegrityError.
- Cash-only portfolios explicitly documented: structural validity != market evidence.
- Full 64 hex char snapshot IDs (snap_<64 hex chars>) with legacy read compatibility.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Configurable freshness limits.
# Temporary Paper defaults; institutional/market policy must explicitly configure SLAs.
PAPER_DEFAULT_MAX_QUOTE_AGE_SECONDS: float = float(os.getenv("MAX_QUOTE_AGE_SECONDS", "60.0"))
PAPER_DEFAULT_MAX_SNAPSHOT_AGE_SECONDS: float = float(os.getenv("MAX_SNAPSHOT_AGE_SECONDS", "60.0"))


class SnapshotIntegrityError(Exception):
    """Raised on immutability violations, hash mismatch, partial writes, or store conflicts."""
    pass


def canonical_evidence_bytes(raw_evidence: dict) -> bytes:
    """Canonical JSON serialization for evidence bytes."""
    return json.dumps(raw_evidence, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_evidence_sha256(raw_evidence: dict) -> str:
    """Deterministic SHA-256 over recoverable canonical evidence bytes."""
    return hashlib.sha256(canonical_evidence_bytes(raw_evidence)).hexdigest()


class EvidencedQuote(BaseModel):
    """Evidence-bearing market quote contract.

    A 1m candle close from yfinance is bar_close data, NOT exchange-native tick/quote data.
    Preserves price_kind='bar_close', interval='1m', source='yfinance', vendor_symbol,
    and actual candle timestamp.
    Binds source_sha256 strictly to recoverable canonical evidence bytes in raw_evidence.
    """
    model_config = ConfigDict(strict=True, extra="forbid")
    ticker: str = Field(min_length=1)
    price: float = Field(gt=0.0)
    currency: str = "BRL"
    source: str = Field(min_length=1)
    price_kind: str = Field(default="bar_close")
    interval: Optional[str] = "1m"
    vendor_symbol: Optional[str] = None
    observed_at: datetime
    collected_at: datetime
    source_ref: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_evidence: Dict[str, Any] = Field(min_length=1)

    @field_validator("price")
    @classmethod
    def validate_price(cls, v: Any) -> float:
        if isinstance(v, bool):
            raise ValueError("boolean is not a valid price")
        if math.isnan(v) or math.isinf(v):
            raise ValueError("price must be a finite number")
        if v <= 0.0:
            raise ValueError("price must be positive")
        return float(v)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("ticker cannot be empty")
        return s

    @model_validator(mode="after")
    def validate_quote_integrity(self):
        times = (self.observed_at, self.collected_at)
        if any(t.tzinfo is None or t.utcoffset() is None for t in times):
            raise ValueError("timezone-aware datetime required")
        if self.observed_at > self.collected_at:
            raise ValueError("observed_at must be <= collected_at")
        expected_hash = compute_evidence_sha256(self.raw_evidence)
        if self.source_sha256 != expected_hash:
            raise ValueError(
                f"source_sha256 mismatch with raw_evidence: {self.source_sha256} != {expected_hash}"
            )
        return self


class PositionSnapshotItem(BaseModel):
    """Position snapshot bound strictly to trades.id (trade_id)."""
    model_config = ConfigDict(strict=True, extra="forbid")
    trade_id: int = Field(ge=1)
    ticker: str = Field(min_length=1)
    shares: float = Field(gt=0.0)
    entry_price: float = Field(gt=0.0)
    current_price: float | None = None
    alocado: float | None = None
    pnl_monetario: float | None = None
    pnl_pct: float | None = None
    quote_observed_at: datetime | None = None
    quote_collected_at: datetime | None = None
    quote_source: str | None = None
    quote_price_kind: str | None = None
    quote_interval: str | None = None
    quote_vendor_symbol: str | None = None
    quote_source_ref: str | None = None
    quote_source_sha256: str | None = None
    quote_raw_evidence: Optional[Dict[str, Any]] = None


class PortfolioBalanceSnapshot(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    patrimonio_total: float
    saldo_disponivel: float
    em_posicoes: float
    saldo_livre: float
    margem_operavel: float | None = None
    currency: str = "BRL"


class ValuationSnapshot(BaseModel):
    """Immutable valuation snapshot with cryptographic integrity binding."""
    model_config = ConfigDict(strict=True, extra="forbid")
    snapshot_id: str = Field(pattern=r"^snap_[0-9a-f]{16,64}$")
    unit: str = Field(default="currency_brl")
    quote_evidence_kind: Literal["market_quotes", "cash_only_no_market_quotes"] = "cash_only_no_market_quotes"
    observed_at: datetime
    collected_at: datetime
    computed_at: datetime
    portfolio: PortfolioBalanceSnapshot
    active_positions: list[PositionSnapshotItem]
    equity: float | None = None
    mtm_total: float | None = None
    is_valid: bool
    reason: str | None = None
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_snapshot_semantics(self) -> ValuationSnapshot:
        # Legacy snapshots omitted quote_evidence_kind and defaulted to cash_only_no_market_quotes.
        # If positions exist, upgrade to market_quotes.
        if len(self.active_positions) > 0 and self.quote_evidence_kind == "cash_only_no_market_quotes":
            object.__setattr__(self, "quote_evidence_kind", "market_quotes")
        return self


def _compute_payload_sha256(payload: dict) -> str:
    """Deterministic canonical JSON SHA-256 excluding self-referential hash and snapshot_id."""
    clean = {k: v for k, v in payload.items() if k not in ("source_sha256", "snapshot_id")}
    encoded = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_target_dir(store_dir: Optional[Path], resolved_db: Path) -> Path:
    if store_dir is not None:
        return Path(store_dir)
    import tempfile
    try:
        temp_dir = Path(tempfile.gettempdir()).resolve()
        if resolved_db.resolve().parent == temp_dir:
            return resolved_db.parent / f"{resolved_db.stem}_snapshots"
    except Exception:
        pass
    return resolved_db.parent / "snapshots"


def create_valuation_snapshot(
    db_path: str | Path | None = None,
    quote_provider: Optional[Callable[[str], Optional[EvidencedQuote]]] = None,
    price_provider: Optional[Callable[[str], Optional[float]]] = None,
    store_dir: Optional[Path] = None,
    clock_now: Optional[datetime] = None,
    max_quote_age_seconds: float = PAPER_DEFAULT_MAX_QUOTE_AGE_SECONDS,
) -> ValuationSnapshot:
    """Create and persist an immutable valuation snapshot.

    - If any active position lacks an evidenced quote or fails validation, valuation fails closed.
    - If legacy price_provider is used, scalar prices are rejected fail-closed.
    - Validates constituent quote freshness: a newly computed snapshot containing an old quote is STILL STALE.
    - Cash-only portfolios (0 active trades): quote_evidence_kind is 'cash_only_no_market_quotes'.
      Structural validity of cash balances does not equate to market quote evidence and does not grant approval.
    - Snapshot ID uses full 64 hex characters (snap_<64 hex chars>).
    """
    resolved_db = Path(db_path) if db_path is not None else PROJECT_ROOT / "data" / "trading_bot.db"
    now = clock_now if clock_now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        now = now.replace(tzinfo=timezone.utc)

    conn = sqlite3.connect(str(resolved_db))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM portfolio ORDER BY id DESC LIMIT 1")
        pf_row = cur.fetchone()
        if not pf_row:
            saldo_disp = 0.0
            em_pos = 0.0
            patrimonio_tot = 0.0
            margem_op = None
        else:
            saldo_disp = float(pf_row["saldo_disponivel"] or 0.0)
            em_pos = float(pf_row["em_posicoes"] or 0.0)
            patrimonio_tot = float(pf_row["patrimonio_total"] or 0.0)
            margem_op = float(pf_row["margem_operavel"]) if pf_row["margem_operavel"] is not None else None

        saldo_livre = round(saldo_disp - em_pos, 4)

        cur.execute("PRAGMA table_info(trades)")
        columns = [row[1] for row in cur.fetchall()]
        id_col = "id" if "id" in columns else "rowid"
        cur.execute(
            f"SELECT {id_col} AS id, ticker, shares, entry_price FROM trades WHERE status = 'active' ORDER BY {id_col} ASC"
        )
        pos_rows = cur.fetchall()
    finally:
        conn.close()

    items: list[PositionSnapshotItem] = []
    mtm_total = 0.0
    is_valid = True
    reason: str | None = None

    if price_provider is not None:
        # Legacy scalar price provider path: strictly rejected fail-closed
        for r in pos_rows:
            trade_id = int(r["id"])
            ticker = str(r["ticker"])
            shares = float(r["shares"] or 0.0)
            entry_p = float(r["entry_price"] or 0.0)
            price = price_provider(ticker)

            is_valid = False
            if price is None or (type(price) in (int, float) and not isinstance(price, bool) and price <= 0):
                reason = f"feed_price_unavailable_for_{ticker}"
            else:
                reason = f"quote_evidence_required_for_{ticker}"

            items.append(
                PositionSnapshotItem(
                    trade_id=trade_id,
                    ticker=ticker,
                    shares=shares,
                    entry_price=entry_p,
                    current_price=None,
                    alocado=None,
                    pnl_monetario=None,
                    pnl_pct=None,
                    quote_observed_at=None,
                    quote_collected_at=None,
                    quote_source=None,
                )
            )
    else:
        # EvidencedQuote provider path
        if quote_provider is None:
            from backend.app.data.feed import get_evidenced_quote
            provider: Callable[[str], Optional[EvidencedQuote]] = get_evidenced_quote
        else:
            provider = quote_provider

        for r in pos_rows:
            trade_id = int(r["id"])
            ticker = str(r["ticker"])
            shares = float(r["shares"] or 0.0)
            entry_p = float(r["entry_price"] or 0.0)

            quote = provider(ticker)
            if quote is None:
                is_valid = False
                reason = reason or f"feed_price_unavailable_for_{ticker}"
                items.append(
                    PositionSnapshotItem(
                        trade_id=trade_id,
                        ticker=ticker,
                        shares=shares,
                        entry_price=entry_p,
                        current_price=None,
                        alocado=None,
                        pnl_monetario=None,
                        pnl_pct=None,
                    )
                )
            elif not isinstance(quote, EvidencedQuote):
                is_valid = False
                reason = reason or f"quote_evidence_required_for_{ticker}"
                items.append(
                    PositionSnapshotItem(
                        trade_id=trade_id,
                        ticker=ticker,
                        shares=shares,
                        entry_price=entry_p,
                        current_price=None,
                        alocado=None,
                        pnl_monetario=None,
                        pnl_pct=None,
                    )
                )
            else:
                # Validate constituent quote freshness at snapshot creation time
                obs_age = (now - quote.observed_at).total_seconds()
                col_age = (now - quote.collected_at).total_seconds()
                quote_stale = (obs_age > max_quote_age_seconds or col_age > max_quote_age_seconds)
                quote_future = ((quote.observed_at - now).total_seconds() > 1.0 or (quote.collected_at - now).total_seconds() > 1.0)

                if quote_future:
                    is_valid = False
                    reason = reason or f"future_quote_timestamp_for_{ticker}"
                elif quote_stale:
                    is_valid = False
                    reason = reason or f"stale_quote_for_{ticker}"

                alocado = round(shares * quote.price, 4)
                pnl_monetario = round((quote.price - entry_p) * shares, 4)
                pnl_pct = round((quote.price - entry_p) / entry_p * 100, 4)
                mtm_total += alocado

                items.append(
                    PositionSnapshotItem(
                        trade_id=trade_id,
                        ticker=ticker,
                        shares=shares,
                        entry_price=entry_p,
                        current_price=quote.price if is_valid else None,
                        alocado=alocado if is_valid else None,
                        pnl_monetario=pnl_monetario if is_valid else None,
                        pnl_pct=pnl_pct if is_valid else None,
                        quote_observed_at=quote.observed_at,
                        quote_collected_at=quote.collected_at,
                        quote_source=quote.source,
                        quote_price_kind=quote.price_kind,
                        quote_interval=quote.interval,
                        quote_vendor_symbol=quote.vendor_symbol,
                        quote_source_ref=quote.source_ref,
                        quote_source_sha256=quote.source_sha256,
                        quote_raw_evidence=quote.raw_evidence,
                    )
                )

    portfolio_snap = PortfolioBalanceSnapshot(
        patrimonio_total=patrimonio_tot,
        saldo_disponivel=saldo_disp,
        em_posicoes=em_pos,
        saldo_livre=saldo_livre,
        margem_operavel=margem_op,
        currency="BRL",
    )

    if len(pos_rows) == 0:
        # Cash-only snapshot: explicitly document that no market quote evidence exists.
        # Structural validity of cash calculation != market evidence != independent approval.
        quote_evidence_kind = "cash_only_no_market_quotes"
        is_valid = True
        reason = None
        computed_equity = round(saldo_livre, 4)
        computed_mtm = 0.0
        observed_at = now
        collected_at = now
    else:
        quote_evidence_kind = "market_quotes"
        if is_valid:
            computed_equity = round(saldo_livre + mtm_total, 4)
            computed_mtm = round(mtm_total, 4)
            observed_at = min(it.quote_observed_at for it in items if it.quote_observed_at is not None)
            collected_at = max(it.quote_collected_at for it in items if it.quote_collected_at is not None)
        else:
            computed_equity = None
            computed_mtm = None
            observed_at = min((it.quote_observed_at for it in items if it.quote_observed_at is not None), default=now)
            collected_at = max((it.quote_collected_at for it in items if it.quote_collected_at is not None), default=now)

    dummy = ValuationSnapshot(
        snapshot_id="snap_" + "0" * 64,
        unit="currency_brl",
        quote_evidence_kind=quote_evidence_kind,
        observed_at=observed_at,
        collected_at=collected_at,
        computed_at=now,
        portfolio=portfolio_snap,
        active_positions=items,
        equity=computed_equity,
        mtm_total=computed_mtm,
        is_valid=is_valid,
        reason=reason,
        source_sha256="0" * 64,
    )
    json_dict = dummy.model_dump(mode="json")
    digest = _compute_payload_sha256(json_dict)
    snapshot_id = f"snap_{digest}"

    snapshot = dummy.model_copy(update={
        "snapshot_id": snapshot_id,
        "source_sha256": digest,
    })

    save_valuation_snapshot(snapshot, store_dir=store_dir, db_path=resolved_db)
    return snapshot


def save_valuation_snapshot(
    snapshot: ValuationSnapshot,
    store_dir: Optional[Path] = None,
    db_path: str | Path | None = None,
) -> Path:
    """Persist snapshot JSON file and SQLite index row.

    Do not claim cross-store atomicity.
    Partial-write behavior:
    - If neither side exists: writes file atomically and inserts DB row.
    - If both exist: succeeds idempotently if hashes and content match, else raises SnapshotIntegrityError.
    - Exact-content retry repairs a missing side if content matches.
    - Conflicting content raises SnapshotIntegrityError.
    """
    resolved_db = Path(db_path) if db_path is not None else PROJECT_ROOT / "data" / "trading_bot.db"
    resolved_db.parent.mkdir(parents=True, exist_ok=True)
    target_dir = _resolve_target_dir(store_dir, resolved_db)
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / f"valuation_{snapshot.snapshot_id}.json"

    content = snapshot.model_dump_json(indent=2)
    expected_sha = snapshot.source_sha256

    # 1. Filesystem check
    if file_path.exists():
        existing_text = file_path.read_text(encoding="utf-8")
        try:
            existing_dict = json.loads(existing_text)
            existing_sha = _compute_payload_sha256(existing_dict)
            if existing_sha != expected_sha:
                raise SnapshotIntegrityError(
                    f"Snapshot file conflict for {snapshot.snapshot_id}: content hash mismatch ({existing_sha} != {expected_sha})"
                )
        except json.JSONDecodeError as e:
            raise SnapshotIntegrityError(f"Corrupted snapshot file on disk for {snapshot.snapshot_id}: {e}")
    else:
        # Atomic write to avoid partial file reads
        tmp_file = target_dir / f".tmp_{snapshot.snapshot_id}_{os.getpid()}.json"
        tmp_file.write_text(content, encoding="utf-8")
        tmp_file.replace(file_path)

    # 2. SQLite check (always ensure both stores are populated)
    conn = sqlite3.connect(str(resolved_db))
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS valuation_snapshots (
                    snapshot_id  TEXT PRIMARY KEY,
                    observed_at  TIMESTAMP,
                    collected_at TIMESTAMP,
                    computed_at  TIMESTAMP,
                    equity       REAL,
                    is_valid     INTEGER NOT NULL,
                    reason       TEXT,
                    payload_json TEXT NOT NULL,
                    sha256       TEXT NOT NULL
                )
                """
            )
            cur = conn.cursor()
            cur.execute(
                "SELECT payload_json, sha256 FROM valuation_snapshots WHERE snapshot_id = ?",
                (snapshot.snapshot_id,),
            )
            row = cur.fetchone()
            if row is not None:
                db_sha = row["sha256"]
                if db_sha != expected_sha:
                    raise SnapshotIntegrityError(
                        f"Snapshot database conflict for {snapshot.snapshot_id}: sha256 mismatch ({db_sha} != {expected_sha})"
                    )
                try:
                    db_dict = json.loads(row["payload_json"])
                    computed_db_sha = _compute_payload_sha256(db_dict)
                    if computed_db_sha != expected_sha:
                        raise SnapshotIntegrityError(
                            f"Snapshot database row corrupted for {snapshot.snapshot_id}: payload digest mismatch"
                        )
                except json.JSONDecodeError as e:
                    raise SnapshotIntegrityError(f"Corrupted SQLite payload for {snapshot.snapshot_id}: {e}")
            else:
                # Plain INSERT INTO; fails closed on concurrent conflicting write
                conn.execute(
                    """
                    INSERT INTO valuation_snapshots (
                        snapshot_id, observed_at, collected_at, computed_at,
                        equity, is_valid, reason, payload_json, sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.snapshot_id,
                        snapshot.observed_at.isoformat(),
                        snapshot.collected_at.isoformat(),
                        snapshot.computed_at.isoformat(),
                        snapshot.equity,
                        1 if snapshot.is_valid else 0,
                        snapshot.reason,
                        content,
                        snapshot.source_sha256,
                    ),
                )
    finally:
        conn.close()

    return file_path


def repair_valuation_snapshot(
    snapshot: ValuationSnapshot,
    store_dir: Optional[Path] = None,
    db_path: str | Path | None = None,
) -> Path:
    """Exact-content retry to repair a missing side of a partially written snapshot."""
    return save_valuation_snapshot(snapshot, store_dir=store_dir, db_path=db_path)


def get_valuation_snapshot(
    snapshot_id: str,
    store_dir: Optional[Path] = None,
    db_path: str | Path | None = None,
) -> Optional[ValuationSnapshot]:
    """Retrieve an existing immutable snapshot by ID.

    Reads publish only when both representations required by the contract are present and match.
    Conflicting content or missing side raises SnapshotIntegrityError.
    No silent fallback to whichever copy parses.
    """
    resolved_db = Path(db_path) if db_path is not None else PROJECT_ROOT / "data" / "trading_bot.db"
    target_dir = _resolve_target_dir(store_dir, resolved_db)
    file_path = target_dir / f"valuation_{snapshot_id}.json"
    if not file_path.exists() and store_dir is None:
        alt_path = PROJECT_ROOT / "data" / "snapshots" / f"valuation_{snapshot_id}.json"
        if alt_path.exists():
            file_path = alt_path

    file_exists = file_path.exists()
    db_exists = resolved_db.exists()
    db_row = None

    if db_exists:
        conn = sqlite3.connect(str(resolved_db))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='valuation_snapshots'")
            if cur.fetchone() is not None:
                cur.execute(
                    "SELECT payload_json, sha256 FROM valuation_snapshots WHERE snapshot_id = ?",
                    (snapshot_id,),
                )
                db_row = cur.fetchone()
        finally:
            conn.close()

    # Case 1: Neither exists
    if not file_exists and db_row is None:
        return None

    # Case 2: Partial write crash window (present in one, missing in other)
    if file_exists and db_row is None:
        raise SnapshotIntegrityError(
            f"Partial write detected for snapshot {snapshot_id}: present in filesystem, missing in database. "
            f"Reads publish only when both stores are present and match. Exact-content retry may repair."
        )

    if not file_exists and db_row is not None:
        raise SnapshotIntegrityError(
            f"Partial write detected for snapshot {snapshot_id}: present in database, missing in filesystem. "
            f"Reads publish only when both stores are present and match. Exact-content retry may repair."
        )

    # Case 3: Both exist — verify content, digests, and cross-store agreement
    file_text = file_path.read_text(encoding="utf-8")
    try:
        file_dict = json.loads(file_text)
    except Exception as e:
        raise SnapshotIntegrityError(f"Failed to parse snapshot JSON file for {snapshot_id}: {e}")

    try:
        db_dict = json.loads(db_row["payload_json"])
    except Exception as e:
        raise SnapshotIntegrityError(f"Failed to parse snapshot SQLite payload for {snapshot_id}: {e}")

    file_sha = _compute_payload_sha256(file_dict)
    file_stored_sha = file_dict.get("source_sha256")
    if file_sha != file_stored_sha:
        raise SnapshotIntegrityError(
            f"Snapshot file {snapshot_id} corrupted or tampered: computed {file_sha} != stored {file_stored_sha}"
        )

    db_sha = _compute_payload_sha256(db_dict)
    db_stored_sha = db_row["sha256"]
    if db_sha != db_stored_sha:
        raise SnapshotIntegrityError(
            f"Snapshot database row {snapshot_id} corrupted or tampered: computed {db_sha} != stored {db_stored_sha}"
        )

    if file_stored_sha != db_stored_sha:
        raise SnapshotIntegrityError(
            f"Conflicting digest between filesystem and database for snapshot {snapshot_id}: "
            f"file={file_stored_sha}, db={db_stored_sha}"
        )

    if file_dict != db_dict:
        raise SnapshotIntegrityError(
            f"Conflicting payload between filesystem and database for snapshot {snapshot_id}"
        )

    return ValuationSnapshot.model_validate_json(file_text)


def get_latest_valuation_snapshot(
    store_dir: Optional[Path] = None,
    db_path: str | Path | None = None,
) -> Optional[ValuationSnapshot]:
    """Retrieve the most recent valuation snapshot where both stores match.

    Fails closed with SnapshotIntegrityError if the most recent snapshot has integrity defects,
    is partially written, or if filesystem and database disagree on the latest snapshot.
    """
    resolved_db = Path(db_path) if db_path is not None else PROJECT_ROOT / "data" / "trading_bot.db"
    target_dir = _resolve_target_dir(store_dir, resolved_db)

    db_latest_id: Optional[str] = None
    if resolved_db.exists():
        conn = sqlite3.connect(str(resolved_db))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='valuation_snapshots'")
            if cur.fetchone() is not None:
                cur.execute(
                    "SELECT snapshot_id FROM valuation_snapshots ORDER BY computed_at DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row is not None:
                    db_latest_id = str(row["snapshot_id"])
        finally:
            conn.close()

    file_latest_id: Optional[str] = None
    if target_dir.exists():
        files = sorted(
            [f for f in target_dir.glob("valuation_snap_*.json") if not f.name.startswith(".tmp_")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if files:
            file_latest_id = files[0].stem.replace("valuation_", "")

    # Case 1: Neither exists
    if db_latest_id is None and file_latest_id is None:
        return None

    # Case 2: Present in database, missing in filesystem (partial write crash window)
    if db_latest_id is not None and file_latest_id is None:
        return get_valuation_snapshot(db_latest_id, store_dir=store_dir, db_path=resolved_db)

    # Case 3: Present in filesystem, missing in database (partial write crash window)
    if db_latest_id is None and file_latest_id is not None:
        return get_valuation_snapshot(file_latest_id, store_dir=store_dir, db_path=resolved_db)

    # Case 4: Both exist and identify the same latest snapshot
    if db_latest_id == file_latest_id:
        return get_valuation_snapshot(db_latest_id, store_dir=store_dir, db_path=resolved_db)

    # Case 5: Both exist but identify different snapshots (partial write of a newer snapshot or conflict)
    try:
        get_valuation_snapshot(file_latest_id, store_dir=store_dir, db_path=resolved_db)
    except SnapshotIntegrityError:
        raise
    try:
        get_valuation_snapshot(db_latest_id, store_dir=store_dir, db_path=resolved_db)
    except SnapshotIntegrityError:
        raise

    raise SnapshotIntegrityError(
        f"Store conflict: latest filesystem snapshot {file_latest_id} does not match latest database snapshot {db_latest_id}"
    )


def is_snapshot_fresh(
    snapshot: ValuationSnapshot,
    active_trade_ids: set[int] | list[int],
    clock_now: Optional[datetime] = None,
    max_snapshot_age_seconds: float = PAPER_DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
    max_quote_age_seconds: float = PAPER_DEFAULT_MAX_QUOTE_AGE_SECONDS,
) -> bool:
    """Validate snapshot validity, age, active trade_id set, and every constituent quote age.

    A newly computed snapshot containing an old quote is STILL STALE.
    Constituent quotes are checked for market quote snapshots.
    Snapshot computed_at age is strictly validated for ALL snapshots (including cash-only).
    """
    if not snapshot.is_valid:
        return False

    now = clock_now if clock_now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        now = now.replace(tzinfo=timezone.utc)

    expected_trade_ids = set(active_trade_ids)
    snapshot_trade_ids = {pos.trade_id for pos in snapshot.active_positions}

    # Trade set match
    if expected_trade_ids != snapshot_trade_ids:
        return False

    # 1. Snapshot computed_at age (applies to ALL snapshots, cash-only and market-quotes)
    snapshot_age = (now - snapshot.computed_at).total_seconds()
    if snapshot_age < 0 or snapshot_age > max_snapshot_age_seconds:
        return False

    # For cash-only portfolios, no market quote evidence exists to expire
    if snapshot.quote_evidence_kind == "cash_only_no_market_quotes":
        return len(expected_trade_ids) == 0

    # 2. Constituent quotes age (for market quote snapshots)
    for pos in snapshot.active_positions:
        if pos.quote_observed_at is None or pos.quote_collected_at is None:
            return False
        observed_age = (now - pos.quote_observed_at).total_seconds()
        collected_age = (now - pos.quote_collected_at).total_seconds()
        if observed_age < 0 or observed_age > max_quote_age_seconds:
            return False
        if collected_age < 0 or collected_age > max_quote_age_seconds:
            return False

    return True
