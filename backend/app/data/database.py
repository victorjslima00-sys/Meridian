import logging
import sqlite3
import datetime
import math
import time
from typing import Dict, Any, List, Optional
from pathlib import Path
from zoneinfo import ZoneInfo

from .accounting import (
    MONETARY_EPSILON,
    AccountingIntegrityError,
    PortfolioIntegrityError,
    validate_monetary_value,
    validate_portfolio_fields,
    validate_and_compute_portfolio_dict,
)

logger = logging.getLogger(__name__)

# Raiz do projeto = 3 níveis acima de backend/app/data/
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DB_PATH = str(PROJECT_ROOT / "data" / "trading_bot.db")

# Datas de snapshot alinhadas ao pregão da B3, não a UTC
TZ_B3 = ZoneInfo("America/Sao_Paulo")


def hoje_b3() -> datetime.date:
    return datetime.datetime.now(TZ_B3).date()


def _alerta_telegram_startup(msg: str) -> None:
    """Alerta best-effort via Telegram durante o boot. Nunca deve mascarar a
    falha real de integridade do banco — se o próprio envio falhar (ex.:
    config ausente), só loga e segue; o RuntimeError do chamador é quem
    efetivamente aborta o startup. Duplicado do padrão em backend/app/main.py
    (não importado de lá para evitar import circular: main.py já importa
    deste módulo)."""
    try:
        from trading_bot.core.config import AppConfig
        from trading_bot.core.telegram import TelegramNotifier
        cfg = AppConfig.load()
        TelegramNotifier(
            cfg.get("notifications", "telegram_bot_token", default=""),
            cfg.get("notifications", "telegram_chat_id", default=""),
        ).send_message(msg)
    except Exception as e:
        logger.error("Falha ao enviar alerta Telegram de integridade: %s", e)


def now_b3() -> datetime.datetime:
    """Datetime timezone-aware no fuso da B3 (para heartbeat do worker)."""
    return datetime.datetime.now(TZ_B3)


def get_connection(isolation_level=None):
    conn = sqlite3.connect(DB_PATH, timeout=15.0, isolation_level=isolation_level)
    conn.execute("PRAGMA busy_timeout=15000;")
    return conn

def init_db():
    conn = get_connection(isolation_level=None)
    try:
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.OperationalError:
            pass

        cursor = conn.cursor()
        max_retries = 30
        for attempt in range(max_retries):
            try:
                cursor.execute("BEGIN IMMEDIATE")
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    time.sleep(0.05 * (attempt + 1))
                else:
                    raise

        # ------------------------------------------------------------------
        # Portfolio Table — Modelo de 3 Baldes
        # ------------------------------------------------------------------
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS portfolio (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            patrimonio_total  REAL DEFAULT 0.0,
            saldo_disponivel  REAL DEFAULT 0.0,
            em_posicoes       REAL DEFAULT 0.0,
            margem_operavel   REAL,
            updated_at        TIMESTAMP
        )
        """
        )

        # Migração suave: schema antigo → novo sem perder dados
        existing = {
            row[1] for row in cursor.execute("PRAGMA table_info(portfolio)").fetchall()
        }
        if "initial_capital" in existing and "patrimonio_total" not in existing:
            # NEXUS-005-B: Safe migration check - fail closed on ambiguous or corrupt capital values
            cursor.execute("SELECT current_capital, invested_capital FROM portfolio")
            legacy_rows = cursor.fetchall()
            for cc, ic in legacy_rows:
                if (
                    cc is None or ic is None
                    or isinstance(cc, bool) or isinstance(ic, bool)
                    or not isinstance(cc, (int, float)) or not isinstance(ic, (int, float))
                    or not math.isfinite(cc) or not math.isfinite(ic)
                    or cc < 0 or ic < 0 or cc < ic
                ):
                    msg = (
                        "Startup failed: Legacy portfolio migration detected ambiguous or "
                        "corrupt capital values. Manual migration required."
                    )
                    logger.error(msg)
                    try:
                        _alerta_telegram_startup(f"🛑 [Meridian] Startup abortado — {msg}")
                    except Exception as alert_err:
                        logger.error("Falha inesperada ao alertar startup abortado: %s", alert_err)
                    raise RuntimeError(msg)

            cursor.execute(
                "ALTER TABLE portfolio ADD COLUMN patrimonio_total REAL DEFAULT 0.0"
            )
            cursor.execute(
                "ALTER TABLE portfolio ADD COLUMN saldo_disponivel REAL DEFAULT 0.0"
            )
            cursor.execute(
                "ALTER TABLE portfolio ADD COLUMN em_posicoes REAL DEFAULT 0.0"
            )
            cursor.execute(
                """
                UPDATE portfolio SET
                    saldo_disponivel = current_capital,
                    em_posicoes      = invested_capital,
                    patrimonio_total = 0.0
            """
            )

        # usabilidade 2e: teto de exposição do bot. NULL = sem teto
        # (comportamento anterior intacto em bancos existentes).
        if "margem_operavel" not in existing:
            cursor.execute("ALTER TABLE portfolio ADD COLUMN margem_operavel REAL")

        # NEXUS-005-B: Portfolio singleton validation & migration
        cursor.execute(
            "SELECT id, patrimonio_total, saldo_disponivel, em_posicoes, margem_operavel FROM portfolio"
        )
        pf_rows = cursor.fetchall()

        if len(pf_rows) > 1:
            msg = (
                f"Startup failed: Database contains multiple portfolio rows ({len(pf_rows)} rows). "
                f"Portfolio singleton invariant violated. Manual remediation required."
            )
            logger.error(msg)
            try:
                _alerta_telegram_startup(f"🛑 [Meridian] Startup abortado — {msg}")
            except Exception as alert_err:
                logger.error("Falha inesperada ao alertar startup abortado: %s", alert_err)
            raise RuntimeError(msg)
        elif len(pf_rows) == 1:
            pid, pat, disp, em_pos, margem = pf_rows[0]
            try:
                validate_portfolio_fields(pat, disp, em_pos, margem)
            except Exception as e:
                msg = (
                    f"Startup failed: Corrupt financial state in existing portfolio row (id={pid}): {e}. "
                    f"Financial domain invariant violated. Manual remediation required."
                )
                logger.error(msg)
                try:
                    _alerta_telegram_startup(f"🛑 [Meridian] Startup abortado — {msg}")
                except Exception as alert_err:
                    logger.error("Falha inesperada ao alertar startup abortado: %s", alert_err)
                raise RuntimeError(msg) from e
        else:
            # len(pf_rows) == 0: Bootstrap canonical initial row
            cursor.execute(
                "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, updated_at) "
                "VALUES (0.0, 0.0, 0.0, ?)",
                (datetime.datetime.now(),),
            )

        # Physical SQLite backstop against multiple rows
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_portfolio_singleton ON portfolio ((1))"
        )

        # Trades Table
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            side TEXT,
            shares REAL,
            entry_price REAL,
            exit_price REAL,
            target_price REAL,
            stop_loss REAL,
            entry_date TIMESTAMP,
            exit_date TIMESTAMP,
            pnl_pct REAL,
            exit_reason TEXT,
            ai_rationale TEXT,
            status TEXT,
            signal_id TEXT,
            decision_price REAL
        )
        """
        )
        
        trades_cols = {
            row[1] for row in cursor.execute("PRAGMA table_info(trades)").fetchall()
        }
        if "signal_id" not in trades_cols:
            cursor.execute("ALTER TABLE trades ADD COLUMN signal_id TEXT")
        if "decision_price" not in trades_cols:
            cursor.execute("ALTER TABLE trades ADD COLUMN decision_price REAL")

        cursor.execute(
            "SELECT signal_id, COUNT(*) FROM trades WHERE signal_id IS NOT NULL "
            "GROUP BY signal_id HAVING COUNT(*) > 1"
        )
        dups = cursor.fetchall()
        if dups:
            raise RuntimeError(
                f"Startup failed: Database contains duplicate strategy signal_ids in trades: {dups}"
            )

        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_strategy_signal_id "
            "ON trades(signal_id) WHERE signal_id IS NOT NULL"
        )


        # 1 posição ativa por ticker (P3-A Etapa 1). Índice PARCIAL (só cobre
        # status='active'): um ticker pode ter várias linhas 'closed' no
        # histórico, só não pode ter duas 'active' ao mesmo tempo. É o
        # backstop real contra a corrida de execute_order — a checagem em
        # Python (SELECT antes do INSERT) sozinha é raçosa (TOCTOU); este
        # índice é quem garante a exclusão mútua de fato via IntegrityError.
        #
        # Verificação defensiva ANTES de criar o índice: um banco existente
        # (upgrade, não uma instalação nova) pode já ter duplicata histórica
        # de posição 'active' por ticker, de antes deste fix. Criar o índice
        # às cegas nesse caso derruba o startup com um IntegrityError
        # críptico, sem dizer qual ticker nem por quê. Detectar e falhar com
        # diagnóstico é fail-closed; falhar às cegas é só quebrado.
        cursor.execute(
            "SELECT ticker, COUNT(*) FROM trades WHERE status = 'active' "
            "GROUP BY ticker HAVING COUNT(*) > 1"
        )
        duplicatas = cursor.fetchall()
        if duplicatas:
            tickers_afetados = ", ".join(
                f"{ticker} ({qtd}x)" for ticker, qtd in duplicatas
            )
            msg = (
                f"Integridade violada em 'trades': {len(duplicatas)} ticker(s) "
                f"com mais de uma posição 'active' simultânea — {tickers_afetados}. "
                f"Resolva manualmente (feche ou mescle as duplicatas na tabela "
                f"trades) antes de subir o serviço. Não é seguro criar o índice "
                f"único idx_trades_one_active_per_ticker com dado inconsistente "
                f"— o startup foi abortado propositalmente."
            )
            logger.error(msg)
            # O alerta é best-effort por definição (ver docstring de
            # _alerta_telegram_startup), mas blindamos o call site também:
            # uma falha aqui — dela própria, não só do envio HTTP que ela já
            # protege — jamais pode impedir o RuntimeError real de propagar.
            try:
                _alerta_telegram_startup(f"🛑 [Meridian] Startup abortado — {msg}")
            except Exception as e:
                logger.error("Falha inesperada ao alertar startup abortado: %s", e)
            raise RuntimeError(msg)

        cursor.execute(
            """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_one_active_per_ticker
        ON trades(ticker) WHERE status = 'active'
        """
        )

        # Equity Snapshots — 1 registro por dia de pregão (data em America/Sao_Paulo)
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS equity_snapshots (
            date       TEXT PRIMARY KEY,
            equity     REAL NOT NULL,
            created_at TIMESTAMP
        )
        """
        )

        # Valuation Snapshots — registros imutáveis com proveniência e hash
        cursor.execute(
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

        cursor.execute("COMMIT")
    except Exception:
        try:
            cursor.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def get_portfolio() -> Dict[str, Any]:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM portfolio")
        rows = cursor.fetchall()
    finally:
        conn.close()

    if len(rows) == 0:
        raise PortfolioIntegrityError(
            "No portfolio row found: database is uninitialized or portfolio state missing."
        )
    if len(rows) > 1:
        raise PortfolioIntegrityError(
            f"Integrity violated: multiple portfolio rows detected ({len(rows)} rows)."
        )

    return validate_and_compute_portfolio_dict(dict(rows[0]))


def set_margem_operavel(valor: float) -> Dict[str, Any]:
    """usabilidade 2e: define o teto de exposição do bot (ação humana).
    Validações fail-closed: nunca negativa, nunca acima do saldo real
    entregue ao bot (saldo_disponivel). Zero é válido — congela novas
    entradas, saídas seguem gerenciadas (mesma semântica FAIL-CLOSED do
    resto do sistema)."""
    try:
        v = validate_monetary_value(valor, "margem_operavel", allow_zero=True)
    except Exception as e:
        return {"ok": False, "error": f"Margem operável inválida: {e}"}

    conn = get_connection(isolation_level="IMMEDIATE")
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, patrimonio_total, saldo_disponivel, em_posicoes, margem_operavel FROM portfolio"
        )
        rows = cursor.fetchall()
        if len(rows) == 0:
            return {"ok": False, "error": "Portfolio não encontrado."}
        if len(rows) > 1:
            return {"ok": False, "error": "Integridade violada: múltiplos portfolios."}

        pid, pat, disponivel, em_pos, margem = rows[0]
        try:
            _, disp_v, _, _, _, _ = validate_portfolio_fields(
                pat, disponivel, em_pos, margem
            )
        except Exception as e:
            return {"ok": False, "error": f"Estado de portfolio corrompido: {e}"}

        if v > disp_v:
            return {
                "ok": False,
                "error": (
                    f"Margem acima do saldo real entregue ao bot "
                    f"(disponível: R$ {disp_v:.2f})."
                ),
            }

        cursor.execute(
            "UPDATE portfolio SET margem_operavel=?, updated_at=? WHERE id=?",
            (v, datetime.datetime.now(), pid),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "margem_operavel": v}


def depositar_no_disponivel(valor: float) -> Dict[str, Any]:
    """Move valor do patrimonio_total → saldo_disponivel (ação humana)."""
    try:
        v = validate_monetary_value(valor, "valor", allow_zero=False)
    except Exception as e:
        return {"ok": False, "error": f"Valor inválido: {e}"}

    conn = get_connection(isolation_level="IMMEDIATE")
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, patrimonio_total, saldo_disponivel, em_posicoes, margem_operavel FROM portfolio"
        )
        rows = cursor.fetchall()
        if len(rows) == 0:
            return {"ok": False, "error": "Portfolio não encontrado."}
        if len(rows) > 1:
            return {"ok": False, "error": "Integridade violada: múltiplos portfolios."}

        pid, patrimonio, disponivel, em_pos, margem = rows[0]
        try:
            pat_v, disp_v, em_pos_v, margem_v, _, _ = validate_portfolio_fields(
                patrimonio, disponivel, em_pos, margem
            )
        except Exception as e:
            return {"ok": False, "error": f"Estado de portfolio corrompido: {e}"}

        if v > pat_v:
            return {
                "ok": False,
                "error": f"Patrimônio insuficiente (total: R$ {pat_v:.2f}).",
            }

        new_pat = round(pat_v - v, 4)
        new_disp = round(disp_v + v, 4)

        if abs((new_pat + new_disp) - (pat_v + disp_v)) > MONETARY_EPSILON:
            return {"ok": False, "error": "Falha na conservação de capital."}

        cursor.execute(
            "UPDATE portfolio SET patrimonio_total=?, saldo_disponivel=?, updated_at=? WHERE id=?",
            (new_pat, new_disp, datetime.datetime.now(), pid),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "ok": True,
        "patrimonio_total": new_pat,
        "saldo_disponivel": new_disp,
    }


def retirar_do_disponivel(valor: float) -> Dict[str, Any]:
    """Move valor do saldo livre → patrimonio_total (ação humana)."""
    try:
        v = validate_monetary_value(valor, "valor", allow_zero=False)
    except Exception as e:
        return {"ok": False, "error": f"Valor inválido: {e}"}

    conn = get_connection(isolation_level="IMMEDIATE")
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, patrimonio_total, saldo_disponivel, em_posicoes, margem_operavel FROM portfolio"
        )
        rows = cursor.fetchall()
        if len(rows) == 0:
            return {"ok": False, "error": "Portfolio não encontrado."}
        if len(rows) > 1:
            return {"ok": False, "error": "Integridade violada: múltiplos portfolios."}

        pid, patrimonio, disponivel, em_pos, margem = rows[0]
        try:
            pat_v, disp_v, em_pos_v, margem_v, saldo_livre, _ = validate_portfolio_fields(
                patrimonio, disponivel, em_pos, margem
            )
        except Exception as e:
            return {"ok": False, "error": f"Estado de portfolio corrompido: {e}"}

        if v > saldo_livre:
            return {
                "ok": False,
                "error": f"Saldo livre insuficiente (livre: R$ {saldo_livre:.2f}).",
            }

        new_pat = round(pat_v + v, 4)
        new_disp = round(disp_v - v, 4)

        if new_disp < -MONETARY_EPSILON:
            return {"ok": False, "error": "Resultado violaria saldo disponível negativo."}
        if abs(new_disp) <= MONETARY_EPSILON:
            new_disp = 0.0

        if new_disp - em_pos_v < -MONETARY_EPSILON:
            return {"ok": False, "error": "Resultado violaria saldo livre negativo."}

        if abs((new_pat + new_disp) - (pat_v + disp_v)) > MONETARY_EPSILON:
            return {"ok": False, "error": "Falha na conservação de capital."}

        cursor.execute(
            "UPDATE portfolio SET patrimonio_total=?, saldo_disponivel=?, updated_at=? WHERE id=?",
            (new_pat, new_disp, datetime.datetime.now(), pid),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "ok": True,
        "patrimonio_total": new_pat,
        "saldo_disponivel": new_disp,
    }


def get_trades() -> List[Dict[str, Any]]:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades ORDER BY exit_date DESC LIMIT 100")
        rows = cursor.fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]

def get_active_trades() -> List[Dict[str, Any]]:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE status = 'active'")
        rows = cursor.fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]

def get_closed_trades() -> List[Dict[str, Any]]:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE status = 'closed' ORDER BY exit_date DESC LIMIT 100")
        rows = cursor.fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]

def get_trade_by_id(trade_id: int) -> Dict[str, Any]:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
        row = cursor.fetchone()
    finally:
        conn.close()
    return dict(row) if row else None
def get_metric_provenance_agent(registry_path: Optional[Path] = None) -> Any:
    from trading_bot.data.metric_provenance import MetricProvenanceAgent
    import os
    env_reg = os.environ.get("METRIC_APPROVALS_PATH")
    reg = Path(registry_path) if registry_path is not None else (Path(env_reg) if env_reg else PROJECT_ROOT / "config" / "metric_approvals.json")
    return MetricProvenanceAgent(PROJECT_ROOT, registry_path=reg)


def _parse_evidence_datetime(dt_val: Any) -> Optional[datetime.datetime]:
    if dt_val is None:
        return None
    if isinstance(dt_val, datetime.datetime):
        if dt_val.tzinfo is None or dt_val.utcoffset() is None:
            return dt_val.replace(tzinfo=datetime.timezone.utc)
        return dt_val.astimezone(datetime.timezone.utc)
    if isinstance(dt_val, str):
        cleaned = dt_val.strip()
        if not cleaned:
            return None
        try:
            parsed = datetime.datetime.fromisoformat(cleaned)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            return parsed.astimezone(datetime.timezone.utc)
        except Exception:
            return None
    return None


def get_risk_metrics(verify_provenance: bool = False, agent: Optional[Any] = None) -> Dict[str, Any]:
    """Descriptive closed-trade statistics; unavailable portfolio risk stays null.

    Database provenance is not proof that upstream prices or fills were verified.
    Generation time below is bound strictly to the real evidence timestamp.
    """
    import math

    conn = get_connection()
    try:
        cursor = conn.cursor()
        columns = {col[1] for col in cursor.execute("PRAGMA table_info(trades)").fetchall()}
        if "exit_date" in columns:
            rows = cursor.execute("SELECT pnl_pct, exit_date FROM trades WHERE status = 'closed'").fetchall()
        else:
            rows = [(r[0], None) for r in cursor.execute("SELECT pnl_pct FROM trades WHERE status = 'closed'").fetchall()]
    finally:
        conn.close()

    values = [row[0] for row in rows]
    parsed_dates = [_parse_evidence_datetime(row[1]) for row in rows]
    valid_dates = [d for d in parsed_dates if d is not None]

    source_path = Path(DB_PATH).resolve()
    if valid_dates:
        evidence_time = max(valid_dates)
    elif source_path.exists():
        evidence_time = datetime.datetime.fromtimestamp(source_path.stat().st_mtime, tz=datetime.timezone.utc)
    else:
        evidence_time = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

    invalid_count = sum(
        not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
        for value in values
    )
    risk_keys = ("sharpe", "sortino", "calmar", "max_drawdown_pct", "var_95_daily")
    result = {key: None for key in (*risk_keys, "win_rate", "avg_win", "avg_loss")}
    unavailable = {key: "validated_portfolio_return_series_required" for key in risk_keys}
    if invalid_count or not values:
        reason = "invalid_closed_trade_returns" if invalid_count else "no_closed_trades"
        unavailable.update({key: reason for key in ("win_rate", "avg_win", "avg_loss")})
    else:
        wins = [value for value in values if value > 0]
        losses = [value for value in values if value < 0]
        result["win_rate"] = len(wins) / len(values)
        # Divide before summing to avoid overflow for finite large observations.
        result["avg_win"] = round(sum(value / len(wins) for value in wins), 2) if wins else None
        result["avg_loss"] = round(sum(value / len(losses) for value in losses), 2) if losses else None
        if not wins:
            unavailable["avg_win"] = "no_winning_trades"
        if not losses:
            unavailable["avg_loss"] = "no_losing_trades"
    result["_metadata"] = {
        "source": "sqlite:trades/status=closed/pnl_pct",
        "generated_at_utc": evidence_time.isoformat() if values else None,
        "owner": "backend.app.data.database.get_risk_metrics",
        "sample_count": len(values),
        "invalid_count": invalid_count,
        "status": "partial" if values and not invalid_count else "unavailable",
        "verification_status": "database_records_not_independently_verified",
        "observation_timestamp": evidence_time.isoformat() if values else None,
        "units": {"win_rate": "fraction", "avg_win": "percent_per_closed_trade", "avg_loss": "percent_per_closed_trade"},
        "definitions": {"win_rate": "positive_returns_divided_by_all_closed_trades", "avg_win": "mean_positive_pnl_pct", "avg_loss": "mean_negative_pnl_pct_excluding_zero"},
        "unavailable_reasons": unavailable,
    }

    if verify_provenance:
        import hashlib
        prov_agent = agent or get_metric_provenance_agent()
        if source_path.exists() and source_path.is_relative_to(PROJECT_ROOT.resolve()):
            source_ref = str(source_path.relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
            source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        else:
            source_ref = "data/trading_bot.db"
            source_sha256 = "0" * 64

        units = {
            "win_rate": "fraction",
            "avg_win": "percent_per_closed_trade",
            "avg_loss": "percent_per_closed_trade",
            "sharpe": "ratio",
            "sortino": "ratio",
            "calmar": "ratio",
            "max_drawdown_pct": "percent",
            "var_95_daily": "currency_brl",
        }
        metrics_provenance = {}
        all_verified = True if values and not invalid_count else False
        for k in (*risk_keys, "win_rate", "avg_win", "avg_loss"):
            val = result[k]
            payload = {
                "metric_name": k,
                "value": float(val) if isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val) else None,
                "unit": units.get(k, "unit"),
                "source_ref": source_ref,
                "source_sha256": source_sha256,
                "observed_at": evidence_time,
                "collected_at": evidence_time,
                "computed_at": evidence_time,
                "owner": "backend.app.data.database.get_risk_metrics",
                "method_version": "1.0",
            }
            eval_res = prov_agent.evaluate(payload)
            result[k] = eval_res["value"]
            metrics_provenance[k] = eval_res
            if eval_res["verification_status"] != "verified":
                all_verified = False

        status_str = "verified" if all_verified and values else "unavailable"
        result["metrics_provenance"] = metrics_provenance
        result["verification_status"] = status_str
        result["value"] = 1.0 if status_str == "verified" else None
        result["_metadata"]["verification_status"] = status_str
        if status_str == "unavailable":
            result["_metadata"]["status"] = "unavailable"

    return result


# ---------------------------------------------------------------------------
# Equity Snapshots — base do Circuit Breaker (drawdowns reais)
# ---------------------------------------------------------------------------

def compute_current_equity() -> Optional[float]:
    """
    Equity real = caixa livre (saldo_disponivel - em_posicoes)
                + valor mark-to-market das posições ativas (shares × preço atual).
    Se o feed falhar para um ticker (preço <= 0 ou None), não há fallback para
    entry_price — retorna None para indicar indisponibilidade real.
    Se o estado persistido do portfolio ou das posições for corrupto/inválido,
    falha closed propagando a respectiva exceção de integridade.
    """
    from .feed import get_current_price

    pf = get_portfolio()
    caixa_livre = pf["saldo_livre"]

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ticker, shares, entry_price FROM trades WHERE status = 'active'"
        )
        posicoes = cursor.fetchall()
    finally:
        conn.close()

    mtm = 0.0
    for pos in posicoes:
        shares = validate_monetary_value(
            pos["shares"], f"shares for active trade {pos['ticker']}", allow_zero=False
        )
        price = get_current_price(pos["ticker"])
        if price is None or price <= 0:
            # Eliminado fallback para entry_price: nunca imputar ou fabricar valor default.
            return None
        price_val = validate_monetary_value(
            price, f"current price for {pos['ticker']}", allow_zero=False
        )
        mtm += shares * price_val

    return round(caixa_livre + mtm, 4)


def save_equity_snapshot(snapshot_date: datetime.date, equity: float) -> None:
    """Grava (ou substitui) o snapshot de equity do dia numa transação única."""
    conn = get_connection(isolation_level="IMMEDIATE")
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO equity_snapshots (date, equity, created_at) VALUES (?, ?, ?)",
            (
                snapshot_date.isoformat(),
                equity,
                datetime.datetime.now(TZ_B3).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def has_snapshot_for(snapshot_date: datetime.date) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM equity_snapshots WHERE date = ? LIMIT 1",
            (snapshot_date.isoformat(),),
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()


def get_equity_snapshots() -> List[Dict[str, Any]]:
    """Histórico completo de equity_snapshots, em ordem cronológica —
    base real da curva de patrimônio (honest-dashboard Bloco 3). Só
    date/equity: nenhum cálculo aqui, quem quiser Sharpe/drawdown real
    calcula a partir da série completa, não inventa em cima dela."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT date, equity FROM equity_snapshots ORDER BY date ASC")
        rows = cursor.fetchall()
    finally:
        conn.close()
    return [{"date": r["date"], "equity": r["equity"]} for r in rows]


def get_equity_refs(ref_date: Optional[datetime.date] = None) -> Optional[Dict[str, float]]:
    """
    Referências de equity para o Circuit Breaker, a partir dos snapshots:
      - initial: snapshot mais antigo (inception)
      - start_of_day: snapshot de ref_date (gravado no início do dia); se ainda
        não existir, o mais recente anterior a ref_date
      - equity_30d: snapshot mais recente com date <= ref_date - 30 dias;
        com histórico curto, usa o mais antigo disponível como proxy
    Retorna None se não houver NENHUM snapshot (chamador deve tratar como
    fail-closed).
    """
    if ref_date is None:
        ref_date = hoje_b3()

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT equity FROM equity_snapshots ORDER BY date ASC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            return None
        initial = row[0]

        cursor.execute(
            "SELECT equity FROM equity_snapshots WHERE date <= ? ORDER BY date DESC LIMIT 1",
            (ref_date.isoformat(),),
        )
        row = cursor.fetchone()
        if not row:
            # Só existem snapshots futuros a ref_date — sem referência confiável
            return None
        start_of_day = row[0]

        cutoff_30d = (ref_date - datetime.timedelta(days=30)).isoformat()
        cursor.execute(
            "SELECT equity FROM equity_snapshots WHERE date <= ? ORDER BY date DESC LIMIT 1",
            (cutoff_30d,),
        )
        row = cursor.fetchone()
        # Histórico curto: snapshot mais antigo serve de proxy para 30d atrás
        equity_30d = row[0] if row else initial
    finally:
        conn.close()

    return {
        "initial": initial,
        "start_of_day": start_of_day,
        "equity_30d": equity_30d,
    }
