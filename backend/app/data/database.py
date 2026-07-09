import sqlite3
import datetime
from typing import Dict, Any, List
from pathlib import Path

# Raiz do projeto = 3 níveis acima de backend/app/data/
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DB_PATH = str(PROJECT_ROOT / "data" / "trading_bot.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
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

    conn = sqlite3.connect(DB_PATH)
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

    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades ORDER BY exit_date DESC")
        rows = cursor.fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
