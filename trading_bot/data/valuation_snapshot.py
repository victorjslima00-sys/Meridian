"""Deterministic, immutable valuation snapshots.

Freezes active positions, balances, feed quotes, units and timestamps into
durable local snapshots. Fails closed immediately if any market quote is missing,
never falling back to entry_price.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class PositionSnapshotItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    ticker: str = Field(min_length=1)
    shares: float = Field(gt=0.0)
    entry_price: float = Field(gt=0.0)
    current_price: float | None = None
    alocado: float | None = None
    pnl_monetario: float | None = None
    pnl_pct: float | None = None
    quote_observed_at: datetime | None = None
    quote_source: str | None = None


class PortfolioBalanceSnapshot(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    patrimonio_total: float
    saldo_disponivel: float
    em_posicoes: float
    saldo_livre: float
    margem_operavel: float | None = None
    currency: str = "BRL"


class ValuationSnapshot(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    snapshot_id: str = Field(min_length=1)
    unit: str = Field(default="currency_brl")
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


def _compute_payload_sha256(payload: dict) -> str:
    """Deterministic canonical JSON SHA-256 excluding self-referential hash."""
    clean = {k: v for k, v in payload.items() if k != "source_sha256"}
    encoded = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_valuation_snapshot(
    db_path: str | Path | None = None,
    price_provider: Optional[Callable[[str], Optional[float]]] = None,
    store_dir: Optional[Path] = None,
    clock_now: Optional[datetime] = None,
) -> ValuationSnapshot:
    """Create and persist an immutable valuation snapshot.

    If any active position lacks a positive feed quote, valuation fails closed:
    equity is None, is_valid is False, reason indicates feed unavailability,
    and entry_price is NEVER used to substitute current market price.
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

        cur.execute(
            "SELECT ticker, shares, entry_price FROM trades WHERE status = 'active' ORDER BY ticker ASC"
        )
        pos_rows = cur.fetchall()
    finally:
        conn.close()

    if price_provider is None:
        from backend.app.data.feed import get_current_price
        provider = get_current_price
    else:
        provider = price_provider

    items: list[PositionSnapshotItem] = []
    mtm_total = 0.0
    is_valid = True
    reason = None

    for r in pos_rows:
        ticker = str(r["ticker"])
        shares = float(r["shares"] or 0.0)
        entry_p = float(r["entry_price"] or 0.0)
        price = provider(ticker)

        if price is None or price <= 0:
            # FAIL-CLOSED: absolutely no fallback to entry_price.
            is_valid = False
            reason = f"feed_price_unavailable_for_{ticker}"
            items.append(
                PositionSnapshotItem(
                    ticker=ticker,
                    shares=shares,
                    entry_price=entry_p,
                    current_price=None,
                    alocado=None,
                    pnl_monetario=None,
                    pnl_pct=None,
                    quote_observed_at=None,
                    quote_source=None,
                )
            )
        else:
            current_p = round(float(price), 4)
            alocado = round(shares * entry_p, 4)
            pnl_mon = round(shares * (current_p - entry_p), 4)
            pnl_pct = round(((current_p / entry_p) - 1.0) * 100.0, 4)
            mtm_pos = shares * current_p
            mtm_total += mtm_pos
            items.append(
                PositionSnapshotItem(
                    ticker=ticker,
                    shares=shares,
                    entry_price=entry_p,
                    current_price=current_p,
                    alocado=alocado,
                    pnl_monetario=pnl_mon,
                    pnl_pct=pnl_pct,
                    quote_observed_at=now,
                    quote_source="market_feed",
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

    if is_valid:
        computed_equity = round(saldo_livre + mtm_total, 4)
        computed_mtm = round(mtm_total, 4)
    else:
        computed_equity = None
        computed_mtm = None

    partial_payload = {
        "unit": "currency_brl",
        "observed_at": now.isoformat(),
        "collected_at": now.isoformat(),
        "computed_at": now.isoformat(),
        "portfolio": portfolio_snap.model_dump(mode="json"),
        "active_positions": [it.model_dump(mode="json") for it in items],
        "equity": computed_equity,
        "mtm_total": computed_mtm,
        "is_valid": is_valid,
        "reason": reason,
    }
    digest = _compute_payload_sha256(partial_payload)
    snapshot_id = f"snap_{digest[:16]}"

    snapshot = ValuationSnapshot(
        snapshot_id=snapshot_id,
        unit="currency_brl",
        observed_at=now,
        collected_at=now,
        computed_at=now,
        portfolio=portfolio_snap,
        active_positions=items,
        equity=computed_equity,
        mtm_total=computed_mtm,
        is_valid=is_valid,
        reason=reason,
        source_sha256=digest,
    )

    save_valuation_snapshot(snapshot, store_dir=store_dir, db_path=resolved_db)
    return snapshot


def save_valuation_snapshot(
    snapshot: ValuationSnapshot,
    store_dir: Optional[Path] = None,
    db_path: str | Path | None = None,
) -> Path:
    """Persist snapshot JSON file and SQLite index row."""
    resolved_db = Path(db_path) if db_path is not None else PROJECT_ROOT / "data" / "trading_bot.db"
    target_dir = Path(store_dir) if store_dir is not None else (resolved_db.parent / "snapshots")
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / f"valuation_{snapshot.snapshot_id}.json"

    content = snapshot.model_dump_json(indent=2)
    file_path.write_text(content, encoding="utf-8")

    if resolved_db.exists():
        conn = None
        try:
            conn = sqlite3.connect(str(resolved_db))
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
                conn.execute(
                    """
                    INSERT OR REPLACE INTO valuation_snapshots (
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
        except Exception:
            pass
        finally:
            if conn:
                conn.close()

    return file_path


def get_valuation_snapshot(
    snapshot_id: str,
    store_dir: Optional[Path] = None,
    db_path: str | Path | None = None,
) -> Optional[ValuationSnapshot]:
    """Retrieve an existing immutable snapshot by ID."""
    resolved_db = Path(db_path) if db_path is not None else PROJECT_ROOT / "data" / "trading_bot.db"
    target_dir = Path(store_dir) if store_dir is not None else (resolved_db.parent / "snapshots")
    file_path = target_dir / f"valuation_{snapshot_id}.json"
    if file_path.exists():
        try:
            return ValuationSnapshot.model_validate_json(file_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    if resolved_db.exists():
        conn = None
        try:
            conn = sqlite3.connect(str(resolved_db))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT payload_json FROM valuation_snapshots WHERE snapshot_id = ?", (snapshot_id,))
            row = cur.fetchone()
            if row and row["payload_json"]:
                return ValuationSnapshot.model_validate_json(row["payload_json"])
        except Exception:
            pass
        finally:
            if conn:
                conn.close()
    return None


def get_latest_valuation_snapshot(
    store_dir: Optional[Path] = None,
    db_path: str | Path | None = None,
) -> Optional[ValuationSnapshot]:
    """Retrieve the most recent valuation snapshot."""
    resolved_db = Path(db_path) if db_path is not None else PROJECT_ROOT / "data" / "trading_bot.db"
    if resolved_db.exists():
        conn = None
        try:
            conn = sqlite3.connect(str(resolved_db))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT payload_json FROM valuation_snapshots ORDER BY computed_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row and row["payload_json"]:
                return ValuationSnapshot.model_validate_json(row["payload_json"])
        except Exception:
            pass
        finally:
            if conn:
                conn.close()

    target_dir = Path(store_dir) if store_dir is not None else (resolved_db.parent / "snapshots")
    if target_dir.exists():
        files = sorted(target_dir.glob("valuation_snap_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files:
            try:
                return ValuationSnapshot.model_validate_json(f.read_text(encoding="utf-8"))
            except Exception:
                continue

    return None
