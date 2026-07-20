import logging
import sqlite3
import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
from zoneinfo import ZoneInfo

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
    # patrimonio_total é a coluna real do "cofre" (capital fora do alcance
    # do bot, só movimentado por depositar_no_disponivel/retirar_do_
    # disponivel) — NUNCA sobrescrever com saldo_disponivel (capital
    # entregue ao bot). Bug real encontrado pelo usuário: os dois
    # apareciam sempre iguais no dashboard porque esta linha existia.
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


# ---------------------------------------------------------------------------
# Equity Snapshots — base do Circuit Breaker (drawdowns reais)
# ---------------------------------------------------------------------------

def compute_current_equity() -> float:
    """
    Equity real = caixa livre (saldo_disponivel - em_posicoes)
                + valor mark-to-market das posições ativas (shares × preço atual).
    Se o feed falhar para um ticker (preço 0.0), usa entry_price como fallback —
    nesse caso a parcela degrada para o capital alocado na entrada.
    """
    from .feed import get_current_price

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT saldo_disponivel, em_posicoes FROM portfolio ORDER BY id DESC LIMIT 1"
        )
        pf = cursor.fetchone()
        if not pf:
            raise RuntimeError("Portfolio não encontrado para cálculo de equity.")
        caixa_livre = (pf["saldo_disponivel"] or 0.0) - (pf["em_posicoes"] or 0.0)

        cursor.execute(
            "SELECT ticker, shares, entry_price FROM trades WHERE status = 'active'"
        )
        posicoes = cursor.fetchall()
    finally:
        conn.close()

    mtm = 0.0
    for pos in posicoes:
        price = get_current_price(pos["ticker"])
        if price <= 0:
            price = pos["entry_price"] or 0.0
        mtm += (pos["shares"] or 0.0) * price

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
