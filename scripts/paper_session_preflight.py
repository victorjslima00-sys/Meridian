"""Meridian Read-Only Paper Session Preflight CLI (NEXUS-003-R1).

Executes comprehensive, zero-mutation verification of runtime environment,
broker isolation, SQLite schema and unique invariants, circuit breaker configuration
and entry gate, storage writability, valuation subsystem, and per-ticker dataset
digest and approval verification.

Guarantees ZERO trade insertions and ZERO portfolio balance mutations.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.app.agents.market_analyst import MarketAnalyst  # noqa: E402
from backend.app.data.database import DB_PATH  # noqa: E402
from backend.app.data.feed import _normalize_ticker  # noqa: E402
from backend.app.markets import get_broker, PaperBroker, resolve_market  # noqa: E402
from backend.app.markets.b3_session import (  # noqa: E402
    B3DayType,
    B3SessionPhase,
    can_enter_new_position,
    can_manage_exits,
    get_b3_day_type,
    get_b3_session_phase,
)
from backend.app.runtime_config import RuntimeConfig  # noqa: E402
from trading_bot.core.config import AppConfig  # noqa: E402
from trading_bot.data.approval import (  # noqa: E402
    PROJECT_ROOT,
    REGISTRY,
    dataset_digest,
    normalize_ohlcv_to_signal_df,
    require_dataset_approval_by_digest,
)
from trading_bot.data.closed_frame import closed_daily_signal_frame  # noqa: E402
from trading_bot.risk.circuit_breaker import CircuitBreaker  # noqa: E402

logger = logging.getLogger("paper_session_preflight")


@dataclass
class TickerPreflightStatus:
    ticker: str
    market_resolved: bool
    data_digest: Optional[str]
    approval_status: str  # PASS / BLOCKED / UNVERIFIED
    approval_reason: str
    analyst_result: Optional[str]
    preflight_verdict: str  # PASS / BLOCKED / UNVERIFIED
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightReport:
    started_at_utc: str
    ended_at_utc: str
    overall_status: str  # PASS / BLOCKED / BLOCKED_SESSION_PHASE / UNVERIFIED
    infrastructure_ready: str  # PASS / BLOCKED
    entry_ready: str  # PASS / BLOCKED_SESSION_PHASE / BLOCKED
    single_writer_check: bool
    b3_calendar_status: str
    session_phase: str
    b3_entry_allowed: bool
    valuation_honesty_status: str
    paper_mode_check: bool
    broker_isolation_check: bool
    db_schema_check: bool
    signal_id_index_check: bool
    active_position_index_check: bool
    circuit_breaker_config_check: bool
    circuit_breaker_can_trade_check: bool
    storage_writable_check: bool
    valuation_subsystem_check: bool
    trade_mutations_count: int
    portfolio_mutations_count: int
    trades_fingerprint_match: bool
    portfolio_fingerprint_match: bool
    ticker_results: List[TickerPreflightStatus] = field(default_factory=list)
    system_messages: List[str] = field(default_factory=list)
    real_broker_calls_verification: str = "UNVERIFIED"
    broker_activation: str = "NOT DETECTED"
    universe_source: str = "configured_universe"
    entry_quote_path_status: str = "READY"
    exit_quote_path_status: str = "READY"


def _compute_db_table_fingerprint(conn: sqlite3.Connection, table_name: str) -> str:
    """Compute deterministic SHA-256 fingerprint of all rows in an SQLite table."""
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {table_name} ORDER BY rowid")
        rows = cursor.fetchall()
        row_bytes = json.dumps(rows, default=str, sort_keys=True).encode("utf-8")
        return hashlib.sha256(row_bytes).hexdigest()
    except Exception:
        return ""


def check_paper_mode(settings_path: str, universe_path: str) -> tuple[bool, str]:
    """Structurally verify supported broker path is PaperBroker and runtime is paper mode."""
    try:
        broker = get_broker("paper")
        if not isinstance(broker, PaperBroker):
            return False, f"get_broker('paper') returned non-PaperBroker: {type(broker)}"

        try:
            get_broker("live")
            return False, "Unsupported broker 'live' was unexpectedly accepted by get_broker"
        except ValueError:
            pass  # Expected: only 'paper' is supported

        cfg = RuntimeConfig.load(settings_path=settings_path, universe_path=universe_path)
        live_flag = os.environ.get("LIVE_TRADING_ENABLED", "0").strip().lower()
        if live_flag in ("1", "true", "yes"):
            return False, "LIVE_TRADING_ENABLED environment flag is active"
        return True, f"Paper mode verified: PaperBroker bound, execution_mode={cfg.execution_mode}"
    except Exception as e:
        return False, f"Failed to verify paper mode: {e}"


def check_broker_isolation(settings_path: str, universe_path: str) -> tuple[bool, str]:
    """Verify no live broker credentials, live configurations, or unauthorized integrations."""
    try:
        app_cfg = AppConfig.load(settings_path=settings_path, universe_path=universe_path)
        broker_cfg = app_cfg.get("broker", default={}) or {}
        if broker_cfg.get("live_execution") is True:
            return False, "Broker configured with live_execution=True"

        live_cred_vars = ["XP_ACCOUNT", "XP_TOKEN", "CLEAR_ACCOUNT", "BTG_API_KEY", "MT5_LOGIN"]
        for var in live_cred_vars:
            if os.environ.get(var):
                return False, f"Live broker environment credential detected: {var}"

        return True, "Broker isolation verified (no live broker credentials or active config)"
    except Exception as e:
        return False, f"Failed to inspect broker configuration: {e}"


def check_database_invariants(db_path: Path) -> tuple[bool, bool, bool, str]:
    """Inspect SQLite schema, signal_id unique index, and active position index without mutating.

    Returns (schema_ok, signal_idx_ok, active_idx_ok, message).
    """
    try:
        if not db_path.is_file():
            return False, False, False, f"BLOCKED: DATABASE_INITIALIZATION_REQUIRED (file not found: {db_path})"

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
        if not cursor.fetchone():
            conn.close()
            return False, False, False, "BLOCKED: DATABASE_INITIALIZATION_REQUIRED (table 'trades' missing)"

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='portfolio'")
        if not cursor.fetchone():
            conn.close()
            return False, False, False, "BLOCKED: DATABASE_INITIALIZATION_REQUIRED (table 'portfolio' missing)"

        cursor.execute("PRAGMA index_list('trades')")
        indexes = cursor.fetchall()
        index_names = {row[1]: row[2] for row in indexes}

        signal_id_ok = False
        if "idx_trades_strategy_signal_id" in index_names and index_names["idx_trades_strategy_signal_id"] == 1:
            signal_id_ok = True

        active_pos_ok = False
        if "idx_trades_one_active_per_ticker" in index_names and index_names["idx_trades_one_active_per_ticker"] == 1:
            active_pos_ok = True

        # Invariant checks: verify no duplicate signal_ids exist
        cursor.execute(
            "SELECT signal_id, COUNT(*) FROM trades WHERE signal_id IS NOT NULL "
            "GROUP BY signal_id HAVING COUNT(*) > 1"
        )
        dups_signal = cursor.fetchall()
        if dups_signal:
            signal_id_ok = False

        # Invariant checks: verify NO duplicate active positions exist per ticker
        cursor.execute(
            "SELECT ticker, COUNT(*) FROM trades WHERE status = 'active' "
            "GROUP BY ticker HAVING COUNT(*) > 1"
        )
        dups_active = cursor.fetchall()
        if dups_active:
            active_pos_ok = False

        conn.close()
        msg_parts = []
        if not signal_id_ok:
            msg_parts.append("signal_id index or uniqueness invariant failed")
        if not active_pos_ok:
            msg_parts.append("active position index or uniqueness invariant failed")

        msg = "Database invariants inspected: " + (", ".join(msg_parts) if msg_parts else "all intact")
        return True, signal_id_ok, active_pos_ok, msg
    except Exception as e:
        return False, False, False, f"Database inspection failed: {e}"


def check_circuit_breaker() -> tuple[bool, bool, str]:
    """Inspect CircuitBreaker configuration load and entry gate (can_trade).

    Returns (config_ok, can_trade_ok, message).
    """
    try:
        cb = CircuitBreaker.from_config()
        config_ok = True
        cfg_msg = (
            f"CircuitBreaker configured: daily_limit={cb.daily_loss_limit:.1%}, "
            f"inception_dd={cb.drawdown_inception:.1%}, rolling_30d_dd={cb.drawdown_rolling_30d:.1%}"
        )
    except Exception as e:
        return False, False, f"CircuitBreaker config load failed: {e}"

    try:
        can_trade_ok = bool(cb.can_trade())
        trade_msg = "entry gate open" if can_trade_ok else "entry gate closed (fail-closed: missing equity refs)"
    except Exception as e:
        can_trade_ok = False
        trade_msg = f"can_trade check threw: {e}"

    return config_ok, can_trade_ok, f"{cfg_msg}; {trade_msg}"


def check_storage_writable(storage_dir: Path) -> tuple[bool, str]:
    """Verify designated session storage path is writable."""
    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
        probe_file = storage_dir / f".probe_{os.getpid()}_{int(datetime.now().timestamp())}.tmp"
        probe_file.write_text("probe", encoding="utf-8")
        probe_file.unlink()
        return True, f"Storage path writable: {storage_dir}"
    except Exception as e:
        return False, f"Storage directory not writable: {storage_dir} ({e})"


def check_single_paper_writer(project_root: Optional[Path] = None) -> tuple[bool, str]:
    """Verify default runtime exposes exactly ONE Paper execution authority (NEXUS-004)."""
    root = (project_root or PROJECT_ROOT).resolve()
    dockerfile = root / "Dockerfile"
    docker_compose = root / "docker-compose.yml"

    # Check Dockerfile for active cron job running legacy script
    if dockerfile.is_file():
        content = dockerfile.read_text(encoding="utf-8")
        for line in content.splitlines():
            line_str = line.strip()
            if line_str.startswith("#"):
                continue
            if "cron" in line_str.lower() and "fase2_paper_trading.py" in line_str:
                return False, "BLOCKED: Alternate Paper order writer active in Dockerfile (cron fase2_paper_trading.py)"

    # Check docker-compose.yml for bot service active in default profile
    if docker_compose.is_file():
        content = docker_compose.read_text(encoding="utf-8")
        import yaml
        try:
            compose_data = yaml.safe_load(content)
            services = compose_data.get("services", {}) if isinstance(compose_data, dict) else {}
            bot_svc = services.get("bot", {})
            if bot_svc:
                profiles = bot_svc.get("profiles", [])
                restart = bot_svc.get("restart", "")
                if "legacy" not in profiles and restart != "no":
                    return False, "BLOCKED: Alternate Paper order writer active in docker-compose.yml ('bot' service default active)"
        except Exception:
            pass

    return True, "Single Paper execution authority verified (legacy cron disabled)"


def check_b3_session_calendar(now: Optional[datetime] = None) -> tuple[bool, str, str, bool, str]:
    """Verify B3 official calendar and determine current session phase (NEXUS-004-R1)."""
    current_dt = now or datetime.now(timezone.utc)
    day_type = get_b3_day_type(current_dt.date())
    phase = get_b3_session_phase(current_dt)
    from backend.app.markets.b3_session import get_session_authority
    can_enter, session_reason, _, _ = get_session_authority().check_authority(current_dt)
    can_exit = can_manage_exits(current_dt)

    calendar_ok = (day_type != B3DayType.UNKNOWN)
    msg = (
        f"B3 Session: day_type={day_type.value}, phase={phase.value}, "
        f"can_enter={can_enter} ({session_reason}), can_exit={can_exit}"
    )
    return calendar_ok, day_type.value, phase.value, can_enter, msg


def check_entry_quote_path() -> tuple[bool, str, str]:
    """Inspect read-only entry quote retrieval contract (NEXUS-004-R1)."""
    try:
        from backend.app.data.feed import get_evidenced_quote
        return True, "READY", "Entry quote contract (get_evidenced_quote) verified available"
    except Exception as e:
        return False, "BLOCKED", f"Entry quote path unavailable: {e}"


def check_exit_quote_path() -> tuple[bool, str, str]:
    """Inspect read-only exit quote extraction contract (NEXUS-004-R1)."""
    try:
        from backend.app.main import extract_exit_evidenced_quote, _price_is_trustworthy
        return True, "READY", "Exit quote contract (extract_exit_evidenced_quote) verified available"
    except Exception as e:
        return False, "BLOCKED", f"Exit quote path unavailable: {e}"


def check_valuation_subsystem() -> tuple[bool, str, str]:
    """Inspect valuation subsystem truthfully (NEXUS-004)."""
    try:
        import trading_bot.data.valuation_snapshot as vs
        assert hasattr(vs, "ValuationSnapshot")
        assert hasattr(vs, "get_latest_valuation_snapshot")
        assert hasattr(vs, "save_valuation_snapshot")
        honesty = "VALUATION_CONTRACT_AVAILABLE / VALUATION_STORE_UNVERIFIED"
        return True, honesty, f"Valuation subsystem: {honesty}"
    except Exception as e:
        return False, "VALUATION_UNAVAILABLE", f"Valuation subsystem check failed: {e}"


def run_paper_preflight(
    settings_path: str = "config/settings.yaml",
    universe_path: str = "config/universe.yaml",
    registry_path: Optional[Path] = None,
    db_path: Optional[Path] = None,
    storage_dir: Optional[Path] = None,
    project_root: Optional[Path] = None,
    tickers: Optional[List[str]] = None,
    max_tickers: Optional[int] = None,
    now_dt: Optional[datetime] = None,
) -> PreflightReport:
    """Run full read-only preflight suite without trade or portfolio mutations."""
    start_utc = datetime.now(timezone.utc).isoformat()
    system_messages = []

    resolved_db = (db_path or Path(DB_PATH)).resolve()
    resolved_storage = (storage_dir or Path(PROJECT_ROOT / "data" / "paper_sessions")).resolve()
    resolved_registry = (registry_path or REGISTRY).resolve()
    resolved_root = (project_root or PROJECT_ROOT).resolve()

    # Capture initial DB row fingerprints and counts
    trades_count_before = 0
    trades_fp_before = ""
    portfolio_fp_before = ""
    if resolved_db.is_file():
        conn_pre = sqlite3.connect(str(resolved_db))
        try:
            cur_pre = conn_pre.cursor()
            cur_pre.execute("SELECT COUNT(*) FROM trades")
            trades_count_before = cur_pre.fetchone()[0]
            trades_fp_before = _compute_db_table_fingerprint(conn_pre, "trades")
            portfolio_fp_before = _compute_db_table_fingerprint(conn_pre, "portfolio")
        except Exception:
            pass
        finally:
            conn_pre.close()

    # 1. System checks
    single_writer_ok, single_writer_msg = check_single_paper_writer(resolved_root)
    system_messages.append(single_writer_msg)

    calendar_ok, day_type_val, phase_val, b3_entry_allowed, session_msg = check_b3_session_calendar(now_dt)
    system_messages.append(session_msg)

    paper_mode_ok, paper_msg = check_paper_mode(settings_path, universe_path)
    system_messages.append(paper_msg)

    broker_iso_ok, broker_msg = check_broker_isolation(settings_path, universe_path)
    system_messages.append(broker_msg)

    db_ok, signal_idx_ok, active_idx_ok, db_msg = check_database_invariants(resolved_db)
    system_messages.append(db_msg)

    cb_cfg_ok, cb_can_trade_ok, cb_msg = check_circuit_breaker()
    system_messages.append(cb_msg)

    storage_ok, storage_msg = check_storage_writable(resolved_storage)
    system_messages.append(storage_msg)

    valuation_ok, val_honesty, valuation_msg = check_valuation_subsystem()
    system_messages.append(valuation_msg)

    entry_qp_ok, entry_qp_status, entry_qp_msg = check_entry_quote_path()
    system_messages.append(entry_qp_msg)

    exit_qp_ok, exit_qp_status, exit_qp_msg = check_exit_quote_path()
    system_messages.append(exit_qp_msg)

    # 2. Universe tickers to check
    universe_loaded_ok = True
    if tickers is not None:
        eval_tickers = [_normalize_ticker(t) for t in tickers if t.strip()]
        universe_source = f"Explicit subset ({len(eval_tickers)} tickers)"
        if not eval_tickers:
            universe_loaded_ok = False
            system_messages.append(
                "BLOCKED: UNIVERSE_UNAVAILABLE - Explicit subset is empty"
            )
    else:
        try:
            app_cfg = AppConfig.load(
                settings_path=settings_path, universe_path=universe_path
            )
            raw_tickers = (
                app_cfg.get("_universe", "tickers", default=[]) or []
            )
            if not raw_tickers:
                eval_tickers = []
                universe_loaded_ok = False
                universe_source = "Unavailable (empty in config)"
                system_messages.append(
                    "BLOCKED: UNIVERSE_UNAVAILABLE - "
                    "Universe tickers empty in config"
                )
            else:
                eval_tickers = [
                    _normalize_ticker(t) for t in raw_tickers if t.strip()
                ]
                universe_source = (
                    f"Configured universe ({len(eval_tickers)} tickers)"
                )
        except Exception as exc:
            eval_tickers = []
            universe_loaded_ok = False
            universe_source = f"Unavailable ({exc})"
            system_messages.append(
                f"BLOCKED: UNIVERSE_UNAVAILABLE - Failed to load universe: {exc}"
            )

    if max_tickers and max_tickers > 0:
        eval_tickers = eval_tickers[:max_tickers]

    ticker_results: List[TickerPreflightStatus] = []

    # 3. Per-ticker evaluation
    for t in eval_tickers:
        details: Dict[str, Any] = {}
        market_resolved = False
        digest: Optional[str] = None
        approval_verdict = "UNVERIFIED"
        approval_reason = ""
        analyst_result: Optional[str] = None
        ticker_verdict = "BLOCKED"

        raw_df = None
        try:
            market = resolve_market(t)
            market_resolved = True
            raw_df = market.fetch_ohlcv(t, period="2y", interval="1d")
        except Exception as e:
            approval_reason = f"Market resolve failed: {e}"
            ticker_verdict = "BLOCKED"

        if market_resolved:
            if raw_df is None:
                approval_reason = "No OHLCV data fetched"
                approval_verdict = "UNVERIFIED"
                ticker_verdict = "UNVERIFIED"
            else:
                try:
                    closed_res = closed_daily_signal_frame(raw_df, ticker=t, as_of=now_dt)
                    details["market_date"] = str(closed_res.market_date)
                    details["decision_bar_date"] = str(closed_res.decision_bar_date)
                    details["today_bar_removed"] = closed_res.today_bar_removed
                    details["session_phase"] = closed_res.session_phase

                    if len(closed_res.closed_df) < 201:
                        bars_cnt = len(closed_res.closed_df)
                        approval_reason = f"Insufficient closed OHLCV data ({bars_cnt} bars)"
                        approval_verdict = "UNVERIFIED"
                        ticker_verdict = "UNVERIFIED"
                    else:
                        norm_df = normalize_ohlcv_to_signal_df(closed_res.closed_df)
                        digest = dataset_digest(norm_df, t)
                        details["digest"] = digest
                        details["bars_count"] = len(norm_df)

                    # Check dataset approval against target registry
                    try:
                        approval_obj = require_dataset_approval_by_digest(
                            dataset_sha256=digest,
                            registry_path=resolved_registry,
                            project_root=resolved_root,
                            settings_path=settings_path,
                        )
                        approval_verdict = "PASS"
                        approval_reason = f"Approved (reviewer={approval_obj.reviewed_by})"
                    except ValueError as ve:
                        approval_verdict = "BLOCKED"
                        approval_reason = f"Registry check: {ve}"
                    except Exception as exc:
                        approval_verdict = "BLOCKED"
                        approval_reason = f"Registry check error: {exc}"

                    # Bind MarketAnalyst to exact frame: call analyze_ohlcv without refetching
                    analyst = MarketAnalyst(t)
                    try:
                        analysis = asyncio.run(
                            analyst.analyze_ohlcv(
                                df=raw_df,
                                registry_path=resolved_registry,
                                project_root=resolved_root,
                                settings_path=settings_path,
                                as_of=now_dt,
                            )
                        )
                        analyst_result = analysis.get("signal", "UNKNOWN")
                        details["analyst_signal"] = analyst_result
                        details["analyst_reason"] = analysis.get("reason", "")
                        details["analyst_strategy"] = analysis.get("strategy_id", "")
                        details["analyst_digest"] = analysis.get("dataset_sha256")

                        if approval_verdict == "PASS":
                            if analyst_result in ("BUY", "HOLD"):
                                ticker_verdict = "PASS"
                            else:
                                ticker_verdict = "BLOCKED"
                                approval_reason += f" (Analyst returned {analyst_result})"
                        else:
                            ticker_verdict = "BLOCKED"

                    except Exception as a_exc:
                        analyst_result = "ERROR"
                        details["analyst_error"] = str(a_exc)
                        ticker_verdict = "BLOCKED"
                        approval_reason += f" (Analyst failed: {a_exc})"

                except Exception as e:
                    approval_verdict = "BLOCKED"
                    approval_reason = f"Data normalization/digest error: {e}"
                    ticker_verdict = "BLOCKED"

        ticker_results.append(
            TickerPreflightStatus(
                ticker=t,
                market_resolved=market_resolved,
                data_digest=digest,
                approval_status=approval_verdict,
                approval_reason=approval_reason,
                analyst_result=analyst_result,
                preflight_verdict=ticker_verdict,
                details=details,
            )
        )

    # Capture state after preflight
    trades_count_after = trades_count_before
    trades_fp_after = trades_fp_before
    portfolio_fp_after = portfolio_fp_before

    if resolved_db.is_file():
        conn_post = sqlite3.connect(str(resolved_db))
        try:
            cur_post = conn_post.cursor()
            cur_post.execute("SELECT COUNT(*) FROM trades")
            trades_count_after = cur_post.fetchone()[0]
            trades_fp_after = _compute_db_table_fingerprint(conn_post, "trades")
            portfolio_fp_after = _compute_db_table_fingerprint(conn_post, "portfolio")
        except Exception:
            pass
        finally:
            conn_post.close()

    trade_mutations = abs(trades_count_after - trades_count_before)
    trades_fp_match = (trades_fp_before == trades_fp_after)
    portfolio_fp_match = (portfolio_fp_before == portfolio_fp_after)

    portfolio_mutations = 0 if portfolio_fp_match else 1
    if not trades_fp_match and trade_mutations == 0:
        trade_mutations = 1

    infrastructure_all_ok = (
        single_writer_ok
        and paper_mode_ok
        and broker_iso_ok
        and db_ok
        and signal_idx_ok
        and active_idx_ok
        and cb_cfg_ok
        and storage_ok
        and valuation_ok
        and entry_qp_ok
        and exit_qp_ok
        and universe_loaded_ok
        and (trade_mutations == 0)
        and (portfolio_mutations == 0)
        and trades_fp_match
        and portfolio_fp_match
    )

    tickers_all_pass = (
        len(ticker_results) > 0
        and all(t.preflight_verdict == "PASS" for t in ticker_results)
    )

    if infrastructure_all_ok:
        infrastructure_ready = "PASS"
    else:
        infrastructure_ready = "BLOCKED"

    any_ticker_blocked = any(t.preflight_verdict == "BLOCKED" for t in ticker_results)

    if infrastructure_ready != "PASS" or not calendar_ok or not universe_loaded_ok or any_ticker_blocked:
        entry_ready = "BLOCKED"
        overall = "BLOCKED"
    elif not b3_entry_allowed:
        entry_ready = "BLOCKED_SESSION_PHASE"
        overall = "BLOCKED_SESSION_PHASE"
    elif not cb_can_trade_ok or not tickers_all_pass:
        entry_ready = "BLOCKED"
        overall = "BLOCKED"
    else:
        entry_ready = "PASS"
        overall = "PASS"

    end_utc = datetime.now(timezone.utc).isoformat()
    broker_act = "NOT DETECTED" if broker_iso_ok else "UNVERIFIED (isolation failed)"

    return PreflightReport(
        started_at_utc=start_utc,
        ended_at_utc=end_utc,
        overall_status=overall,
        infrastructure_ready=infrastructure_ready,
        entry_ready=entry_ready,
        single_writer_check=single_writer_ok,
        b3_calendar_status=day_type_val,
        session_phase=phase_val,
        b3_entry_allowed=b3_entry_allowed,
        valuation_honesty_status=val_honesty,
        paper_mode_check=paper_mode_ok,
        broker_isolation_check=broker_iso_ok,
        db_schema_check=db_ok,
        signal_id_index_check=signal_idx_ok,
        active_position_index_check=active_idx_ok,
        circuit_breaker_config_check=cb_cfg_ok,
        circuit_breaker_can_trade_check=cb_can_trade_ok,
        storage_writable_check=storage_ok,
        valuation_subsystem_check=valuation_ok,
        entry_quote_path_status=entry_qp_status,
        exit_quote_path_status=exit_qp_status,
        trade_mutations_count=trade_mutations,
        portfolio_mutations_count=portfolio_mutations,
        trades_fingerprint_match=trades_fp_match,
        portfolio_fingerprint_match=portfolio_fp_match,
        ticker_results=ticker_results,
        system_messages=system_messages,
        real_broker_calls_verification="UNVERIFIED",
        broker_activation=broker_act,
        universe_source=universe_source,
    )


def format_report(report: PreflightReport) -> str:
    lines = []
    lines.append("=" * 80)
    lines.append("MERIDIAN PAPER SESSION PREFLIGHT REPORT (NEXUS-004)")
    lines.append("=" * 80)
    lines.append(f"Started at (UTC):       {report.started_at_utc}")
    lines.append(f"Ended at (UTC):         {report.ended_at_utc}")
    lines.append(f"Overall Status:         {report.overall_status}")
    lines.append(f"Infrastructure Ready:   {report.infrastructure_ready}")
    lines.append(f"Entry Ready:            {report.entry_ready}")
    lines.append(f"B3 Session Phase:       {report.session_phase} (Entry Allowed: {report.b3_entry_allowed})")
    lines.append(f"B3 Calendar Status:     {report.b3_calendar_status}")
    lines.append(f"Universe Source:   {report.universe_source}")

    tm_status = " (ZERO MUTATION VERIFIED)" if (
        report.trade_mutations_count == 0 and report.trades_fingerprint_match
    ) else " (MUTATION DETECTED)"
    pm_status = " (ZERO MUTATION VERIFIED)" if (
        report.portfolio_mutations_count == 0 and report.portfolio_fingerprint_match
    ) else " (MUTATION DETECTED)"

    lines.append(f"Trade Mutations:   {report.trade_mutations_count}{tm_status}")
    lines.append(f"Portfolio Mutated: {report.portfolio_mutations_count}{pm_status}")
    lines.append(f"Broker Calls:      {report.real_broker_calls_verification}")
    lines.append(f"Broker Activation: {report.broker_activation}")
    lines.append("-" * 80)
    lines.append("SYSTEM CHECKS:")
    lines.append(f"  [ {'PASS' if report.single_writer_check else 'FAIL'} ] Single Paper Execution Authority")
    lines.append(f"  [ {'PASS' if report.paper_mode_check else 'FAIL'} ] Paper Mode Active (PaperBroker bound)")
    lines.append(f"  [ {'PASS' if report.broker_isolation_check else 'FAIL'} ] Broker Isolation")
    lines.append(f"  [ {'PASS' if report.db_schema_check else 'FAIL'} ] Database Schema Inspection (read-only)")
    lines.append(f"  [ {'PASS' if report.signal_id_index_check else 'FAIL'} ] Signal ID Unique Index & Invariant")
    lines.append(f"  [ {'PASS' if report.active_position_index_check else 'FAIL'} ] Active Position Index & Invariant")
    lines.append(f"  [ {'PASS' if report.circuit_breaker_config_check else 'FAIL'} ] Circuit Breaker Config Load")
    cb_gate_str = "PASS" if report.circuit_breaker_can_trade_check else "BLOCKED"
    lines.append(f"  [ {cb_gate_str} ] Circuit Breaker Entry Gate (can_trade)")
    lines.append(f"  [ {'PASS' if report.storage_writable_check else 'FAIL'} ] Storage Path Writable")
    lines.append(f"  [ {'PASS' if report.valuation_subsystem_check else 'FAIL'} ] Valuation Subsystem ({report.valuation_honesty_status})")
    lines.append(f"  [ {report.entry_quote_path_status} ] Entry Quote Path (get_evidenced_quote)")
    lines.append(f"  [ {report.exit_quote_path_status} ] Exit Quote Path (extract_exit_evidenced_quote)")
    lines.append("-" * 80)
    lines.append("TICKER EVALUATION:")
    lines.append(f"{'Ticker':<10} | {'Resolve':<8} | {'Digest':<18} | {'Approval':<10} | {'Verdict':<10} | {'Reason'}")
    lines.append("-" * 80)
    for tr in report.ticker_results:
        dig_str = (tr.data_digest[:14] + "...") if tr.data_digest else "None"
        res_str = "PASS" if tr.market_resolved else "FAIL"
        row_msg = (
            f"{tr.ticker:<10} | {res_str:<8} | {dig_str:<18} | "
            f"{tr.approval_status:<10} | {tr.preflight_verdict:<10} | {tr.approval_reason}"
        )
        lines.append(row_msg)
    lines.append("=" * 80)
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Meridian Read-Only Paper Session Preflight"
    )
    parser.add_argument("--settings", default="config/settings.yaml", help="Path to settings.yaml")
    parser.add_argument("--universe", default="config/universe.yaml", help="Path to universe.yaml")
    parser.add_argument("--registry", default=None, help="Path to data_approvals.json")
    parser.add_argument("--db", default=None, help="Path to SQLite database")
    parser.add_argument("--storage", default=None, help="Path to paper session storage")
    parser.add_argument("--tickers", default=None, help="Comma-separated ticker list")
    parser.add_argument("--max-tickers", type=int, default=None, help="Limit number of tickers to check")

    args = parser.parse_args(argv)

    ticker_list = None
    if args.tickers:
        ticker_list = [t.strip() for t in args.tickers.split(",") if t.strip()]

    report = run_paper_preflight(
        settings_path=args.settings,
        universe_path=args.universe,
        registry_path=Path(args.registry) if args.registry else None,
        db_path=Path(args.db) if args.db else None,
        storage_dir=Path(args.storage) if args.storage else None,
        tickers=ticker_list,
        max_tickers=args.max_tickers,
    )

    print(format_report(report))
    return 0 if report.overall_status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
