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
                    saldo_disponivel = COALESCE(current_capital, 0.0),
                    em_posicoes      = COALESCE(invested_capital, 0.0),
                    patrimonio_total = 0.0
            """
            )

        # usabilidade 2e: teto de exposição do bot. NULL = sem teto
        # (comportamento anterior intacto em bancos existentes).
        if "margem_operavel" not in existing:
            cursor.execute("ALTER TABLE portfolio ADD COLUMN margem_operavel REAL")

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

        # Inicializar portfolio se vazio
        cursor.execute("SELECT COUNT(*) FROM portfolio")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, updated_at) VALUES (0.0, 0.0, 0.0, ?)",
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
            "saldo_disponivel": 0.0,
            "em_posicoes": 0.0,
            "saldo_livre": 0.0,
            "margem_operavel": None,
            "saldo_operavel": 0.0,
        }

    d = dict(row)
    # patrimonio_total é a coluna real do "cofre" (capital fora do alcance
    # do bot, só movimentado por depositar_no_disponivel/retirar_do_
    # disponivel) — NUNCA sobrescrever com saldo_disponivel (capital
    # entregue ao bot). Bug real encontrado pelo usuário: os dois
    # apareciam sempre iguais no dashboard porque esta linha existia.
    d["saldo_livre"] = round(d.get("saldo_disponivel", 0) - d.get("em_posicoes", 0), 4)
    # usabilidade 2e — fonte única do capital operável do bot: com
    # margem_operavel definida, ela é um TETO de exposição total
    # (em_posicoes + novas alocações ≤ margem); sem margem (NULL),
    # operável = livre, comportamento anterior. Todo consumidor (sizing
    # do laço automático, rota manual, executor, UI) lê ESTE campo —
    # nunca recalcula por conta própria.
    margem = d.get("margem_operavel")
    if margem is None:
        d["saldo_operavel"] = d["saldo_livre"]
    else:
        d["saldo_operavel"] = round(
            min(d["saldo_livre"], max(0.0, margem - d.get("em_posicoes", 0))), 4
        )
    return d


def set_margem_operavel(valor: float) -> Dict[str, Any]:
    """usabilidade 2e: define o teto de exposição do bot (ação humana).
    Validações fail-closed: nunca negativa, nunca acima do saldo real
    entregue ao bot (saldo_disponivel). Zero é válido — congela novas
    entradas, saídas seguem gerenciadas (mesma semântica FAIL-CLOSED do
    resto do sistema)."""
    if valor < 0:
        return {"ok": False, "error": "Margem operável não pode ser negativa."}

    conn = get_connection(isolation_level="IMMEDIATE")
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, saldo_disponivel FROM portfolio ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if not row:
            return {"ok": False, "error": "Portfolio não encontrado."}

        pid, disponivel = row
        if valor > disponivel:
            return {
                "ok": False,
                "error": (
                    f"Margem acima do saldo real entregue ao bot "
                    f"(disponível: R$ {disponivel:.2f})."
                ),
            }

        cursor.execute(
            "UPDATE portfolio SET margem_operavel=?, updated_at=? WHERE id=?",
            (valor, datetime.datetime.now(), pid),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "margem_operavel": valor}


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
        if price is None or price <= 0:
            # Eliminado fallback para entry_price: nunca imputar ou fabricar valor default.
            return None
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
