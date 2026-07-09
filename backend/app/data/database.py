import sqlite3
import datetime
from typing import Dict, Any, List
from pathlib import Path

# Raiz do projeto = 3 níveis acima de backend/app/data/
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DB_PATH = str(PROJECT_ROOT / "data" / "trading_bot.db")


def get_connection(isolation_level=None):
    conn = sqlite3.connect(DB_PATH, isolation_level=isolation_level)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # ------------------------------------------------------------------
        # Portfolio Table — Modelo de 3 Baldes
        # ------------------------------------------------------------------
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS portfolio (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            patrimonio_total  REAL DEFAULT 0.0,
            saldo_disponivel  REAL DEFAULT 100.0,
            em_posicoes       REAL DEFAULT 0.0,
            updated_at        TIMESTAMP
        )
        """
        )

        # Migração suave: schema antigo → novo sem perder dados
        existing = {
            row[1] for row in cursor.execute("PRAGMA table_info(portfolio)").fetchall()
        }
        if "initial_capital" in existing and "patrimonio_total" not in existing:
            cursor.execute(
                "ALTER TABLE portfolio ADD COLUMN patrimonio_total REAL DEFAULT 0.0"
            )
            cursor.execute(
                "ALTER TABLE portfolio ADD COLUMN saldo_disponivel REAL DEFAULT 100.0"
            )
            cursor.execute(
                "ALTER TABLE portfolio ADD COLUMN em_posicoes REAL DEFAULT 0.0"
            )
            cursor.execute(
                """
                UPDATE portfolio SET
                    saldo_disponivel = COALESCE(current_capital, 100.0),
                    em_posicoes      = COALESCE(invested_capital, 0.0),
                    patrimonio_total = 0.0
            """
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
            status TEXT
        )
        """
        )

        # Inicializar portfolio se vazio
        cursor.execute("SELECT COUNT(*) FROM portfolio")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, updated_at) VALUES (0.0, 100.0, 0.0, ?)",
                (datetime.datetime.now(),),
            )

        conn.commit()
    finally:
        conn.close()


def get_portfolio() -> Dict[str, Any]:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM portfolio ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        return {
            "patrimonio_total": 0.0,
            "saldo_disponivel": 100.0,
            "em_posicoes": 0.0,
            "saldo_livre": 100.0,
        }

    d = dict(row)
    d["saldo_livre"] = round(d.get("saldo_disponivel", 0) - d.get("em_posicoes", 0), 4)
    return d


def depositar_no_disponivel(valor: float) -> Dict[str, Any]:
    """Move valor do patrimonio_total → saldo_disponivel (ação humana)."""
    if valor <= 0:
        return {"ok": False, "error": "Valor deve ser positivo."}

    conn = get_connection(isolation_level="IMMEDIATE")
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, patrimonio_total, saldo_disponivel FROM portfolio ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if not row:
            return {"ok": False, "error": "Portfolio não encontrado."}

        pid, patrimonio, disponivel = row
        if valor > patrimonio:
            return {
                "ok": False,
                "error": f"Patrimônio insuficiente (total: R$ {patrimonio:.2f}).",
            }

        cursor.execute(
            "UPDATE portfolio SET patrimonio_total=?, saldo_disponivel=?, updated_at=? WHERE id=?",
            (patrimonio - valor, disponivel + valor, datetime.datetime.now(), pid),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "ok": True,
        "patrimonio_total": patrimonio - valor,
        "saldo_disponivel": disponivel + valor,
    }


def retirar_do_disponivel(valor: float) -> Dict[str, Any]:
    """Move valor do saldo livre → patrimonio_total (ação humana)."""
    if valor <= 0:
        return {"ok": False, "error": "Valor deve ser positivo."}

    conn = get_connection(isolation_level="IMMEDIATE")
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, patrimonio_total, saldo_disponivel, em_posicoes FROM portfolio ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if not row:
            return {"ok": False, "error": "Portfolio não encontrado."}

        pid, patrimonio, disponivel, em_pos = row
        livre = disponivel - em_pos

        if valor > livre:
            return {
                "ok": False,
                "error": f"Saldo livre insuficiente (livre: R$ {livre:.2f}).",
            }

        cursor.execute(
            "UPDATE portfolio SET patrimonio_total=?, saldo_disponivel=?, updated_at=? WHERE id=?",
            (patrimonio + valor, disponivel - valor, datetime.datetime.now(), pid),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "ok": True,
        "patrimonio_total": patrimonio + valor,
        "saldo_disponivel": disponivel - valor,
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
def get_risk_metrics() -> Dict[str, float]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT pnl_pct FROM trades WHERE status = 'closed'")
        rows = cursor.fetchall()
        
        pnls = [r[0] for r in rows if r[0] is not None]
        
        if not pnls:
            return {
                "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0,
                "max_drawdown_pct": 0.0, "var_95_daily": 0.0,
                "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0
            }
            
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        win_rate = len(wins) / len(pnls) if pnls else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        
        import math
        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls) if len(pnls) > 1 else 0.0
        std_dev = math.sqrt(variance)
        
        # Simple approximations for dashboard display based on trade returns
        sharpe = (mean_pnl / std_dev) if std_dev > 0 else 0.0
        
        downside_variance = sum(p**2 for p in losses) / len(pnls) if len(pnls) > 0 else 0.0
        downside_std = math.sqrt(downside_variance)
        sortino = (mean_pnl / downside_std) if downside_std > 0 else 0.0
        
        # Max drawdown approx: largest single loss or accumulated loss
        max_drawdown = min(losses) if losses else 0.0
        var_95 = sorted(pnls)[int(len(pnls) * 0.05)] if len(pnls) >= 20 else max_drawdown
        
        return {
            "sharpe": round(sharpe, 2),
            "sortino": round(sortino, 2),
            "calmar": round(sharpe * 0.8, 2), # Approximated
            "max_drawdown_pct": round(max_drawdown, 2),
            "var_95_daily": round(var_95, 2),
            "win_rate": round(win_rate, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
        }
    finally:
        conn.close()
