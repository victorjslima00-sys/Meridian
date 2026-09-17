import datetime
from pathlib import Path
from .data.feed import get_current_price
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import random
from contextlib import asynccontextmanager, suppress
from pydantic import BaseModel

from . import worker_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Ciclo de vida da app (substitui @app.on_event, deprecated).
    Sobe os DOIS supervisores — entrada (worker_supervisor) e saída
    (exit_loop_supervisor, P3-A Etapa 4) — cada um com contabilidade de
    restart isolada; no shutdown, cancela as duas tasks limpo.
    """
    from .data.database import init_db
    from .security import validate_security_config
    from .runtime_config import RuntimeConfig
    validate_security_config()
    RuntimeConfig.load()
    init_db()
    # FAIL-FAST: config de risco inválida derruba o boot com erro claro,
    # em vez de deixar o bot operar com thresholds quebrados.
    from trading_bot.risk.circuit_breaker import CircuitBreaker
    CircuitBreaker.from_config()

    from trading_bot.core.coordinator import CentralCoordinator
    coord = CentralCoordinator()
    coord.register_worker(
        name="ai_committee_worker",
        coro_fn=ai_committee_worker,
        interval_seconds=worker_state.SCAN_INTERVAL_SECONDS,
        max_restarts=worker_state.MAX_RESTARTS,
        backoff_cap_seconds=worker_state.BACKOFF_CAP_SECONDS,
        is_critical=False,
        supervision=worker_state.state,
        alert_fn=_alerta_telegram,
    )
    coord.register_worker(
        name="exit_loop",
        coro_fn=exit_loop,
        interval_seconds=worker_state.EXIT_INTERVAL_SECONDS,
        max_restarts=worker_state.MAX_RESTARTS,
        backoff_cap_seconds=worker_state.BACKOFF_CAP_SECONDS,
        is_critical=True,
        on_exhausted=worker_state.state.set_exit_gate_sticky_block,
        supervision=worker_state.state.exit_supervision,
        alert_fn=_alerta_telegram,
    )
    app.state.coordinator = coord

    worker_state.state.mark_starting()
    task = asyncio.create_task(worker_supervisor())
    task.add_done_callback(_log_if_supervisor_died)
    app.state.worker_task = task

    worker_state.state.exit_supervision.mark_starting()
    exit_task = asyncio.create_task(exit_loop_supervisor())
    exit_task.add_done_callback(_log_if_exit_supervisor_died)
    app.state.exit_task = exit_task

    try:
        yield
    finally:
        task.cancel()
        exit_task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        with suppress(asyncio.CancelledError):
            await exit_task
        with suppress(Exception):
            await coord.stop()


app = FastAPI(title="Meridian AI Core", lifespan=lifespan)

import os

ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173"  # dev local
).split(",")

from fastapi import Depends
from .security import verify_api_key

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/status")
def get_status():
    from .runtime_config import RuntimeConfig
    runtime = RuntimeConfig.load()
    # Reflete o estado real do worker: nunca "online" com o loop morto/stale.
    snap = worker_state.state.snapshot()
    return {
        "status": snap["status"],           # online | degraded | stopped
        "mode": "paper_trading",
        "execution_mode": runtime.execution_mode,
        "worker_alive": snap["worker_alive"],
        "worker_status": snap["worker_status"],
        "last_scan_at": snap["last_scan_at"],
        # P3-A Etapa 3: dois sinais separados do exit_loop — atividade
        # (o laço está rodando) e efetividade (o laço está de fato
        # avaliando stop/target com preço confiável). Expostos à parte de
        # last_scan_at (que é só do laço lento de entradas) para que quem
        # observa consiga distinguir "laço de saída girando" de "laço de
        # saída girando E protegendo".
        "last_exit_activity_at": snap["last_exit_activity_at"],
        "last_effective_exit_scan_at": snap["last_effective_exit_scan_at"],
        "restart_count": snap["restart_count"],
        # honest-dashboard Bloco 1: portão de entradas exposto pronto —
        # o frontend não decide nem calcula nada, só exibe.
        "exit_restart_count": snap["exit_restart_count"],
        "exit_gate_sticky_block": snap["exit_gate_sticky_block"],
        "motivos_bloqueio": snap["motivos_bloqueio"],
    }


import sqlite3
import logging
from .data.database import (
    get_portfolio,
    get_trades,
    init_db,
    depositar_no_disponivel,
    retirar_do_disponivel,
    DB_PATH,
    has_snapshot_for,
    compute_current_equity,
    save_equity_snapshot,
)

logger = logging.getLogger(__name__)


def _alerta_telegram(msg: str) -> None:
    """Alerta best-effort via Telegram; nunca derruba o worker."""
    try:
        from trading_bot.core.config import AppConfig
        from trading_bot.core.telegram import TelegramNotifier
        cfg = AppConfig.load()
        TelegramNotifier(
            cfg.get("notifications", "telegram_bot_token", default=""),
            cfg.get("notifications", "telegram_chat_id", default=""),
        ).send_message(msg)
    except Exception as e:
        logger.error(f"Falha ao enviar alerta Telegram: {e}")

from .agents.market_analyst import MarketAnalyst
from .agents.risk_manager import RiskManager
from .agents.executor import ExecutorAgent

import math
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union


# -----------------------------------------------------------------------
# Deduplicação de alerta (P3-A Etapa 2d)
# -----------------------------------------------------------------------
# exit_loop roda a cada ~5s (EXIT_INTERVAL_SECONDS). Sem deduplicação, uma
# condição de preço não confiável PERSISTENTE (feed real fora do ar, não
# só rate limit transitório — o cache de preço em feed.py já resolve o
# caso transitório) dispararia um alerta Telegram a cada iteração,
# indefinidamente. Alarme que grita sem parar vira alarme ignorado.
#
# Alerta na primeira ocorrência da condição para uma CHAVE (ticker, ou um
# identificador de sistema — ver Etapa 4); silencia repetições da MESMA
# condição; reenvia um lembrete após um cooldown com o problema ainda
# ativo (nunca silêncio total — CLAUDE.md: "loops autônomos nunca morrem
# em silêncio"); e trata uma recuperação seguida de nova falha como
# condição NOVA (alerta de novo), não como continuação da anterior.
ALERT_COOLDOWN_SECONDS = 600  # 10 min — tests podem monkeypatchar
EXIT_LOOP_EXHAUSTED_REMINDER_SECONDS = 1800  # 30 min (P3-A Etapa 4)

_last_alert_state: dict = {}
# chave -> {"reason": str, "last_sent_at": float (monotonic)}
# chave é o ticker para alertas de preço; para alertas de sistema
# (Etapa 4) é um identificador fixo tipo "__exit_loop__".


def _should_alert(key: str, reason: str, cooldown_seconds: Optional[float] = None) -> bool:
    """Mecanismo geral de deduplicação (P3-A Etapa 2d, generalizado na
    Etapa 4 para o lembrete de exit_loop esgotado, que usa um cooldown
    próprio mais longo). True se um alerta deve ser enviado agora para
    esta chave+motivo. Sempre registra o envio (efeito colateral) quando
    retorna True, para que a PRÓXIMA chamada saiba que já alertou."""
    cooldown = cooldown_seconds if cooldown_seconds is not None else ALERT_COOLDOWN_SECONDS
    now = time.monotonic()
    prev = _last_alert_state.get(key)
    if prev is None or prev["reason"] != reason:
        _last_alert_state[key] = {"reason": reason, "last_sent_at": now}
        return True
    if now - prev["last_sent_at"] >= cooldown:
        prev["last_sent_at"] = now
        return True
    return False


def _should_alert_price_untrustworthy(ticker: str, reason: str) -> bool:
    """Wrapper mantendo nome/assinatura da Etapa 2d — ver _should_alert
    para o mecanismo geral."""
    return _should_alert(ticker, reason)


def _clear_alert_state(key: str) -> None:
    """Chamado quando a condição se resolve (ex.: preço volta a ser
    confiável). A PRÓXIMA falha para esta chave é tratada como ocorrência
    nova — alerta de novo, não fica presa ao cooldown da falha anterior."""
    _last_alert_state.pop(key, None)


def _formatar_posicoes_abertas_para_alerta() -> str:
    """Lista as posições ativas (ticker, entrada, stop, alvo) para o
    alerta de desistência do exit_loop (P3-A Etapa 4, exigência
    obrigatória) — é a informação acionável que falta num alerta genérico
    de "algo grave aconteceu". Quando a proteção morre, saber QUAIS
    posições ficaram expostas é o que importa, não só que algo quebrou."""
    from .data.database import get_active_trades

    try:
        trades = get_active_trades()
    except Exception as e:
        return f"(falha ao listar posições abertas: {e})"

    if not trades:
        return "(nenhuma posição ativa no momento)"

    linhas = [
        f"- {t['ticker']}: entrada R$ {t['entry_price']:.2f}, "
        f"stop R$ {t['stop_loss']:.2f}, alvo R$ {t['target_price']:.2f}"
        for t in trades
    ]
    return "\n".join(linhas)


from trading_bot.data.valuation_snapshot import (
    EvidencedQuote,
    PAPER_DEFAULT_MAX_QUOTE_AGE_SECONDS,
    compute_evidence_sha256,
)

PAPER_EXIT_MAX_OBSERVATION_AGE_SECONDS: float = float(PAPER_DEFAULT_MAX_QUOTE_AGE_SECONDS)


def _price_is_trustworthy(
    price: Any,
    open_: Any = None,
    high: Any = None,
    low: Any = None,
    observed_at: Optional[datetime.datetime] = None,
    collected_at: Optional[datetime.datetime] = None,
    max_age_seconds: Optional[float] = None,
    now: Optional[datetime.datetime] = None,
) -> bool:
    """FAIL-CLOSED para decisões de saída (NEXUS-004-R1):
    Rejeita:
    - None
    - bool (isinstance(price, bool) == True não é preço numérico)
    - não numérico
    - NaN
    - +Inf / -Inf (valores não finitos)
    - price <= 0
    - velas com Open, High e Low todos zerados (candle incompleto do yfinance)
    - timestamp sem fuso (naive) ou futuro (> 5s tolerância)
    - cotação com idade superior a max_age_seconds (stale price)
    - observed_at posterior a collected_at (inconsistência causal)
    """
    if price is None or isinstance(price, bool):
        return False
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(price_f) or price_f <= 0.0:
        return False

    if open_ is not None or high is not None or low is not None:
        for val in (open_, high, low):
            if val is not None:
                if isinstance(val, bool):
                    return False
                try:
                    vf = float(val)
                    if not math.isfinite(vf) or vf < 0.0:
                        return False
                except (TypeError, ValueError):
                    return False

        if open_ is not None and high is not None and low is not None:
            if float(open_) == 0.0 and float(high) == 0.0 and float(low) == 0.0:
                return False

    # Validação de frescor temporal se fornecido
    if observed_at is not None or collected_at is not None:
        from zoneinfo import ZoneInfo
        import pandas as pd
        tz_b3 = ZoneInfo("America/Sao_Paulo")
        current_time = now or datetime.datetime.now(tz_b3)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=tz_b3)

        # Naive provider timestamps: REJECT. Do not invent timezone semantics (NEXUS-004-R1).
        parsed_dates = []
        for ts_cand in (observed_at, collected_at):
            if ts_cand is not None:
                if not isinstance(ts_cand, datetime.datetime):
                    try:
                        ts_cand = pd.to_datetime(ts_cand)
                        if isinstance(ts_cand, pd.Timestamp):
                            ts_cand = ts_cand.to_pydatetime()
                    except Exception:
                        return False
                if ts_cand.tzinfo is None:
                    return False
                parsed_dates.append(ts_cand.astimezone(tz_b3))
            else:
                parsed_dates.append(None)

        obs_tz, col_tz = parsed_dates[0], parsed_dates[1]

        # Non-causal check if both timestamps provided
        if obs_tz is not None and col_tz is not None:
            if obs_tz > col_tz + datetime.timedelta(seconds=1.0):
                return False

        limit = max_age_seconds if max_age_seconds is not None else PAPER_EXIT_MAX_OBSERVATION_AGE_SECONDS
        if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(limit) or limit <= 0.0:
            return False

        if obs_tz is not None:
            if (obs_tz - current_time).total_seconds() > 5.0:
                return False
            if (current_time - obs_tz).total_seconds() > limit:
                return False
        if col_tz is not None:
            if (col_tz - current_time).total_seconds() > 5.0:
                return False
            if (current_time - col_tz).total_seconds() > limit:
                return False

    return True


def extract_exit_evidenced_quote(
    ticker: str,
    df: Any,
    collected_at: Optional[datetime.datetime] = None,
) -> Optional[Any]:
    """NON-AUTHORITATIVE helper: extracts synthetic exit quote from DataFrame for legacy testing.

    DEMOTED (NEXUS-004-R3): Authoritative automatic exit execution MUST use
    backend.app.data.feed.get_evidenced_quote(...) to preserve feed provider provenance,
    actual collection timestamp, and provider evidence hash.
    """
    if df is None or getattr(df, "empty", True):
        return None
    try:
        from trading_bot.data.valuation_snapshot import EvidencedQuote, compute_evidence_sha256
        import pandas as pd
        from zoneinfo import ZoneInfo

        tz_b3 = ZoneInfo("America/Sao_Paulo")
        candle = df.iloc[-1]
        date_val = candle.get("date") if "date" in candle else (
            candle.get("datetime") if "datetime" in candle else candle.get("index")
        )
        if date_val is None:
            return None

        if not isinstance(date_val, datetime.datetime):
            date_val = pd.to_datetime(date_val)
            if isinstance(date_val, pd.Timestamp):
                date_val = date_val.to_pydatetime()

        if date_val.tzinfo is None:
            return None  # Naive timestamp rejected

        obs_tz = date_val.astimezone(tz_b3)
        col_tz = collected_at or datetime.datetime.now(tz_b3)
        if col_tz.tzinfo is None:
            return None
        col_tz = col_tz.astimezone(tz_b3)

        close_p = float(candle["close"])
        if not math.isfinite(close_p) or close_p <= 0.0:
            return None

        raw_ev = {
            "ticker": ticker.upper(),
            "close": close_p,
            "source": "exit_scan",
            "price_kind": "bar_close",
            "interval": "1m",
            "vendor_symbol": ticker.upper(),
            "observed_at": obs_tz.isoformat(),
            "collected_at": col_tz.isoformat(),
        }
        sha = compute_evidence_sha256(raw_ev)
        return EvidencedQuote(
            ticker=ticker.upper(),
            price=close_p,
            currency="BRL",
            source="exit_scan",
            price_kind="bar_close",
            interval="1m",
            vendor_symbol=ticker.upper(),
            observed_at=obs_tz,
            collected_at=col_tz,
            source_ref=f"exit_scan://{ticker}",
            source_sha256=sha,
            raw_evidence=raw_ev,
        )
    except Exception as exc:
        logger.warning("[%s] Failed to extract exit EvidencedQuote: %s", ticker, exc)
        return None


async def _run_exit_scan() -> bool:
    """PHASE 1 isolada (P3-A Etapa 2): percorre SÓ tickers com posição
    ativa — não o universo inteiro. Custo independe do tamanho do universo,
    o que resolve a latência de stop-loss descrita no BACKLOG.md (antes,
    a checagem de stop de um ticker só rodava 1x por ciclo completo do
    laço lento, e um ciclo passava de 10 min com 50 tickers).

    Aplica breakeven + stop/target e fecha via close_order — já idempotente
    (CAS, P3-A Etapa 1): mesmo que esta função rode concorrentemente com
    outra chamada para o mesmo trade, no máximo uma credita o portfolio.

    Returns:
        True se esta passada foi PLENAMENTE efetiva — todo ticker ativo
        teve preço confiável avaliado, ou não havia nenhum ticker ativo
        (nada podia ter ficado desprotegido). False se ao menos um ticker
        ativo teve preço não confiável nesta passada (ver P3-A Etapa 3 —
        heartbeat granular: "o laço está rodando" e "o laço está
        protegendo" são sinais distintos, um vivo mas inefetivo não pode
        passar por saudável).
    """
    from .data.database import get_connection

    conn = get_connection()
    try:
        active_tickers = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT ticker FROM trades WHERE status = 'active'"
            ).fetchall()
        ]
    finally:
        conn.close()

    all_trustworthy = True

    # Fase 1 Commit 1: o dado de mercado do caminho MAIS quente (proteção de
    # stop, a cada ~5s) passa a vir pela abstração de Mercado, não do
    # yfinance direto. A B3Market delega para feed.fetch_recent_data com os
    # mesmos argumentos — comportamento idêntico, inclusive o cache e o TTL.
    #
    # Commit 1b: resolve_market POR TICKER (fail-closed) — um ticker que não
    # casa nenhum mercado conhecido não vira B3 silenciosamente; é pulado e
    # a passada é marcada não-efetiva (mesma categoria de "sem avaliação"
    # que preço não confiável). Isola a falha ao ticker: um símbolo
    # malformado não pode cegar a proteção de stop de TODAS as posições.
    from .markets import resolve_market

    for ticker in active_tickers:
        try:
            market = resolve_market(ticker)
        except ValueError:
            logger.error(
                "Exit scan: ticker %s sem mercado resolvido — pulado "
                "(fail-closed).", ticker
            )
            all_trustworthy = False
            continue

        exit_ttl = worker_state.exit_price_cache_ttl_seconds()
        # Authoritative market evidence from feed provider (NEXUS-004-R3)
        from .data.feed import get_evidenced_quote
        exit_quote = await asyncio.to_thread(get_evidenced_quote, ticker, ttl=exit_ttl)
        if exit_quote is None:
            logger.warning(
                "Exit scan: evidência estruturada de saída indisponível para %s — mantendo posição (fail-closed)",
                ticker,
            )
            if _should_alert_price_untrustworthy(ticker, "untrustworthy_price"):
                await asyncio.to_thread(
                    _alerta_telegram,
                    f"⚠️ [Meridian] Exit scan: preço não confiável para {ticker} "
                    f"(None) — posição mantida (fail-closed).",
                )
            all_trustworthy = False
            continue

        raw = exit_quote.raw_evidence or {}
        if not _price_is_trustworthy(
            exit_quote.price,
            open_=raw.get("open"),
            high=raw.get("high"),
            low=raw.get("low"),
            observed_at=exit_quote.observed_at,
            collected_at=exit_quote.collected_at,
        ):
            logger.warning(
                "Exit scan: preço não confiável para %s (%r) — mantendo "
                "posição, nenhuma ação tomada.", ticker, exit_quote.price
            )
            # Log sempre acontece (barato); o Telegram é deduplicado —
            # exit_loop roda a cada poucos segundos, e uma condição
            # persistente não pode virar um alerta a cada iteração.
            if _should_alert_price_untrustworthy(ticker, "untrustworthy_price"):
                await asyncio.to_thread(
                    _alerta_telegram,
                    f"⚠️ [Meridian] Exit scan: preço não confiável para {ticker} "
                    f"({exit_quote.price!r}) — posição mantida (fail-closed).",
                )
            all_trustworthy = False
            continue

        # Stop/target decision and close order both use the exact evidenced price
        current_price = exit_quote.price

        # Preço confiável de novo: limpa o estado de alerta deste ticker,
        # para que uma falha FUTURA seja tratada como condição nova (não
        # presa ao cooldown de uma falha antiga já resolvida).
        _clear_alert_state(ticker)

        from .data.database import get_connection

        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, side, entry_price, target_price, stop_loss FROM "
                "trades WHERE ticker = ? AND status = 'active'",
                (ticker,),
            )
            active_trade = cursor.fetchone()
            if not active_trade:
                # Fechado por outra via entre o SELECT DISTINCT e agora
                # (ex.: fechamento manual via API). Nada a fazer.
                continue

            trade_id, side, entry_price, target_price, stop_loss = active_trade

            # Atualiza PnL ao vivo (mesma lógica de antes, agora isolada aqui)
            if entry_price > 0:
                live_pnl_pct = (
                    ((current_price - entry_price) / entry_price) * 100
                    if side == "BUY"
                    else ((entry_price - current_price) / entry_price) * 100
                )
            else:
                live_pnl_pct = 0.0
            cursor.execute(
                "UPDATE trades SET pnl_pct = ? WHERE id = ? AND status = 'active'",
                (live_pnl_pct, trade_id),
            )
            if cursor.rowcount == 0:
                # Concurrent close happened, do not proceed with breakeven or close
                continue
            conn.commit()

            # Breakeven (50% do caminho até o alvo)
            if (
                side == "BUY"
                and target_price > entry_price
                and stop_loss < entry_price
            ):
                halfway = entry_price + (target_price - entry_price) * 0.5
                if current_price >= halfway:
                    cursor.execute(
                        "UPDATE trades SET stop_loss = ? WHERE id = ? AND status = 'active'",
                        (entry_price, trade_id),
                    )
                    if cursor.rowcount == 0:
                        continue
                    conn.commit()
                    stop_loss = entry_price
                    await broadcast_log(
                        "RiskManager",
                        f"Breakeven ativado para {ticker}: Stop Loss movido para R$ {entry_price:.2f}",
                        "success",
                    )
            elif (
                side == "SELL"
                and target_price < entry_price
                and stop_loss > entry_price
            ):
                halfway = entry_price - (entry_price - target_price) * 0.5
                if current_price <= halfway:
                    cursor.execute(
                        "UPDATE trades SET stop_loss = ? WHERE id = ? AND status = 'active'",
                        (entry_price, trade_id),
                    )
                    if cursor.rowcount == 0:
                        continue
                    conn.commit()
                    stop_loss = entry_price
                    await broadcast_log(
                        "RiskManager",
                        f"Breakeven ativado para {ticker}: Stop Loss movido para R$ {entry_price:.2f}",
                        "success",
                    )

            close_trade = False
            close_reason = ""
            if side == "BUY":
                if target_price > 0 and current_price >= target_price:
                    close_trade, close_reason = True, f"Take Profit hit at {current_price}"
                elif stop_loss > 0 and current_price <= stop_loss:
                    close_trade, close_reason = True, f"Stop Loss hit at {current_price}"
            elif side == "SELL":
                if target_price > 0 and current_price <= target_price:
                    close_trade, close_reason = True, f"Take Profit hit at {current_price}"
                elif stop_loss > 0 and current_price >= stop_loss:
                    close_trade, close_reason = True, f"Stop Loss hit at {current_price}"
        finally:
            conn.close()

        if close_trade:
            await broadcast_log(
                "System",
                f"Closing active trade on {ticker}: {close_reason}",
                "warning",
            )
            executor = ExecutorAgent()
            try:
                res = executor.close_order(trade_id, current_price, close_reason, evidence=exit_quote)
            except Exception as exc:
                logger.exception("Exit scan: exceção ao fechar ordem para trade %s (%s): %s", trade_id, ticker, exc)
                res = {"status": "exception", "reason": str(exc)}

            if res.get("status") == "closed":
                await broadcast_log(
                    "ExecutorAgent",
                    f"Closed trade! PnL: {res.get('pnl_pct', 0.0):.2f}%",
                    "success",
                )
            else:
                logger.error(
                    "Exit scan: close_order não fechou posição para trade %s (%s) [status=%s, reason=%s]",
                    trade_id, ticker, res.get("status"), res.get("reason"),
                )
                await broadcast_log(
                    "ExecutorAgent",
                    f"Falha ao fechar trade {trade_id} ({ticker}): status={res.get('status')} motivo={res.get('reason')}",
                    "error",
                )
                all_trustworthy = False
        else:
            await broadcast_log(
                "System",
                f"{ticker} já possui posição aberta. Monitorando (Current: {current_price})...",
                "info",
            )

    return all_trustworthy


async def _avaliar_portao_de_entradas() -> tuple[bool, list[str]]:
    """
    PORTÃO ÚNICO de decisão sobre novas entradas (P3-A Etapa 4). Antes
    desta etapa, só o circuit breaker decidia; agora a saúde do exit_loop
    também é motivo de bloqueio — e os dois respondem pela MESMA via,
    nunca por caminhos separados que podem um dia divergir ("um diz
    liberado, outro diz bloqueado" num sistema que move dinheiro é
    inaceitável).

    Motivos acumuláveis (mais de um pode estar ativo ao mesmo tempo):
    - "circuit_breaker": circuit breaker ativo ou indisponível
      (fail-closed, comportamento já existente antes da Etapa 4).
    - "exit_loop_unhealthy": saída não está viva+efetiva AGORA — bloqueio
      DINÂMICO, se resolve sozinho quando a saída volta a ficar saudável.
    - "exit_loop_exhausted": saída esgotou os restarts — bloqueio STICKY,
      permanece mesmo que a saída volte a responder; só reinício do
      processo limpa (ver worker_state.WorkerState.exit_gate_sticky_block).

    Returns:
        (liberado, motivos) — liberado é True só se motivos estiver vazio.
    """
    motivos: list[str] = []

    try:
        from trading_bot.risk.circuit_breaker import CircuitBreaker
        pode_operar = await asyncio.to_thread(
            CircuitBreaker.from_config().can_trade
        )
        if not pode_operar:
            motivos.append("circuit_breaker")
    except Exception as e:
        logger.error(f"Circuit breaker indisponível ({e}) — bloqueando entradas.")
        motivos.append("circuit_breaker")

    if worker_state.state.exit_gate_sticky_block:
        motivos.append("exit_loop_exhausted")
    elif not worker_state.state.is_exit_loop_healthy():
        motivos.append("exit_loop_unhealthy")

    worker_state.state.mark_gate_evaluated(motivos)
    return (len(motivos) == 0, motivos)


# (Fase 1 Commit 2) LLM_CALL_SPACING_SECONDS foi REMOVIDO: espaçava as
# chamadas Gemini do laço de entradas para não estourar o tier gratuito.
# Com o sinal agora DETERMINÍSTICO (Donchian, cálculo local sobre dados
# diários cacheados), não há mais chamada de LLM no laço — nem rate limit a
# espaçar. O que sobrou disso é o ciclo muito mais rápido.


async def _run_one_scan_cycle():
    """
    Uma iteração completa do laço LENTO (entradas): snapshot diário de
    equity, avaliação do circuit breaker e varredura do universo em busca
    de novas oportunidades. Isolada em função própria para que
    ai_committee_worker() possa envolvê-la em try/except sem que uma falha
    pontual derrube o loop.

    A gestão de posições ativas (antiga PHASE 1) saiu daqui — ver
    exit_loop()/_run_exit_scan(), que roda isolada e rápida (P3-A Etapa 2).
    Isso resolve a latência de stop-loss: antes, o stop de uma posição só
    era reavaliado 1x por ciclo completo deste laço lento, que passava de
    10 min com 50 tickers (ver BACKLOG.md).
    """
    print("Starting AI committee scan loop...", flush=True)

    try:
        from trading_bot.core.config import AppConfig
        cfg = AppConfig.load()
        raw_tickers = cfg.get("_universe", "tickers", default=[]) or []
        tickers_to_watch = [f"{t}.SA" if not str(t).endswith(".SA") else str(t) for t in raw_tickers if t and str(t).strip()]
    except Exception as exc:
        logger.error("Falha ao carregar universo de produção (%s) — ciclo abortado (fail-closed)", exc)
        await broadcast_log("System", f"Falha ao carregar universo: {exc} — ciclo de entrada abortado", "error")
        return


    # Snapshot diário de equity (data do pregão) — base do circuit breaker.
    # Fase 1 Commit 1: a data vem do CALENDÁRIO DO MERCADO, não de um
    # helper fixo da B3 — num mercado 24/7 (cripto) o conceito de "dia de
    # pregão" é outro, e é a implementação de Market que decide.
    try:
        from .markets import get_market

        hoje = get_market().today()
        if not has_snapshot_for(hoje):
            equity = await asyncio.to_thread(compute_current_equity)
            if equity is not None:
                save_equity_snapshot(hoje, equity)
                await broadcast_log(
                    "System", f"Equity snapshot {hoje}: R$ {equity:.2f}", "info"
                )
            else:
                logger.warning(f"Equity snapshot {hoje} suspenso: cotação indisponível no feed.")
    except Exception as e:
        logger.error(f"Falha no snapshot diário de equity: {e}")
        await broadcast_log(
            "System", f"Falha no snapshot diário de equity: {e}", "error"
        )
        await asyncio.to_thread(
            _alerta_telegram, f"⚠️ [Meridian] Falha no snapshot diário de equity: {e}"
        )

    # Portão ÚNICO de entradas (P3-A Etapa 4) — ver _avaliar_portao_de_entradas.
    # A gestão de saídas (exit_loop, independente deste laço) roda sempre,
    # mesmo com entradas bloqueadas por qualquer motivo.
    entradas_liberadas, motivos_bloqueio = await _avaliar_portao_de_entradas()
    from .runtime_config import RuntimeConfig
    runtime = RuntimeConfig.load()
    if not entradas_liberadas:
        await broadcast_log(
            "System",
            f"Entradas bloqueadas ({', '.join(motivos_bloqueio)}) — "
            f"gestão de saídas segue normal.",
            "warning",
        )
        if "exit_loop_exhausted" in motivos_bloqueio:
            # Lembrete periódico enquanto o sticky persistir — mesmo
            # padrão "não silencia, não spama" do dedup de preço (Etapa
            # 2d), cooldown próprio mais longo (30 min).
            if _should_alert(
                "__exit_loop__", "exhausted", EXIT_LOOP_EXHAUSTED_REMINDER_SECONDS
            ):
                posicoes = _formatar_posicoes_abertas_para_alerta()
                await asyncio.to_thread(
                    _alerta_telegram,
                    "🛑 [Meridian] Lembrete: exit_loop ainda PARADO (restarts "
                    "esgotados), entradas bloqueadas até reinício manual do "
                    f"processo. Posições sem avaliação de stop:\n{posicoes}",
                )

    if not tickers_to_watch:
        logger.error("Universo configurado vazio ou indisponível — ciclo abortado (fail-closed)")
        await broadcast_log("System", "Universo configurado vazio — ciclo de entrada abortado", "warning")
        return

    # Autonomous session authority gate (NEXUS-004-R1)
    from backend.app.markets.b3_session import get_session_authority
    session_allowed, session_reason, _, _ = get_session_authority().check_authority()
    if not session_allowed:
        logger.info("Autonomous entry gate closed: %s — skipping scan cycle", session_reason)
        await broadcast_log(
            "System",
            f"Sessão B3 não autorizada para novas entradas autônomas ({session_reason}) — gestão de saídas segue normal.",
            "info",
        )
        return

    for ticker in tickers_to_watch:
        print(f"Scanning {ticker}...", flush=True)

        # Guarda explícita (P3-A Etapa 2b): sem a antiga PHASE 1 aqui, o
        # `continue` que impedia (como efeito colateral) uma segunda
        # entrada num ticker já posicionado também sumiu — a gestão dessas
        # posições passou para o exit_loop, isolado. Sem esta guarda, o
        # índice único idx_trades_one_active_per_ticker (P3-A Etapa 1)
        # ainda impediria a duplicata, mas via IntegrityError em vez de
        # simplesmente pular — comportamento correto, não um erro.
        from .data.database import get_connection

        _conn = get_connection()
        try:
            ja_possui_posicao = _conn.execute(
                "SELECT 1 FROM trades WHERE ticker = ? AND status = 'active'",
                (ticker,),
            ).fetchone()
        finally:
            _conn.close()
        if ja_possui_posicao:
            continue

        # --- ENTRY LOOP (Find New Opportunities) ---
        if not entradas_liberadas or not runtime.autonomous_entries_enabled:
            continue
        await broadcast_log("System", f"Scanning {ticker} for entry...", "info")

        # 1. Analyst — sinal DETERMINÍSTICO Donchian (Fase 1 Commit 2), sem
        # LLM. O antigo asyncio.sleep(LLM_CALL_SPACING_SECONDS) SAIU junto com
        # as chamadas Gemini: não há mais rate limit a espaçar (o sinal é
        # cálculo local sobre dados diários cacheados). Removê-lo também
        # encurta drasticamente o ciclo.
        analyst = MarketAnalyst(ticker)
        analysis = await analyst.analyze()
        await broadcast_log(
            "MarketAnalyst",
            f"{ticker} Analysis: {analysis['signal']} - {analysis['reason']}",
            "info",
        )

        # 2. Risk Manager (com checagem de correlação)
        if analysis.get("signal") != "HOLD":
            await broadcast_log(
                "RiskManager",
                f"Evaluating {analysis.get('signal')} on {ticker}...",
                "warning",
            )
            pf = get_portfolio()
            # usabilidade 2e: o sizing dimensiona sobre o capital OPERÁVEL
            # (teto de exposição definido pelo usuário, quando houver), não
            # sobre o livre bruto — ordem já nasce dentro da margem. O
            # executor ainda re-checa o teto dentro da transação (defesa em
            # profundidade contra corrida entre duas entradas).
            saldo_operavel = pf.get("saldo_operavel", pf.get("saldo_livre", 0.0))
            em_posicoes = pf.get("em_posicoes", 0.0)

            # Buscar todos os tickers com posição ativa para checar correlação
            from .data.database import get_connection
            _conn = get_connection()
            try:
                open_tickers = [
                    row[0]
                    for row in _conn.execute(
                        "SELECT DISTINCT ticker FROM trades WHERE status='active'"
                    ).fetchall()
                ]
            finally:
                _conn.close()

            # Contract validation
            from .agents.contracts import ApprovedExecutionIntent, TypedSignal
            try:
                sig = TypedSignal.model_validate(analysis)
            except Exception as e:
                await broadcast_log(
                    "MarketAnalyst",
                    f"Contract validation failed for {ticker}: {e}",
                    "error",
                )
                continue

            # Sizing alinhado ao backtest (Fase 1 Commit 2) DENTRO da margem
            # operável (usabilidade 2e): o capital em posições entra para
            # formar o total_equity que o Kelly fixo do backtest usa, mas a
            # base de caixa é o operável — a posição nasce limitada pelo teto
            # que o usuário definiu, não pelo livre bruto.
            rm = RiskManager(saldo_livre=saldo_operavel, em_posicoes=em_posicoes)
            decision = rm.evaluate_trade(
                sig, ticker=ticker, open_tickers=open_tickers
            )

            if decision.approved:
                await broadcast_log("RiskManager", decision.reason, "success")

                # Obtain fresh EvidencedQuote (NEXUS-004)
                from .data.feed import get_evidenced_quote
                quote = await asyncio.to_thread(get_evidenced_quote, ticker)
                if quote is None:
                    await broadcast_log(
                        "ExecutorAgent",
                        f"EvidencedQuote fresca indisponível para {ticker} — entrada bloqueada (fail-closed)",
                        "error",
                    )
                    continue

                # 3. Executor
                try:
                    intent = ApprovedExecutionIntent(
                        signal=sig,
                        risk_decision=decision,
                        execution_quote=quote,
                    )
                except Exception as e:
                    await broadcast_log("ExecutorAgent", f"Execution intent validation failed: {e}", "error")
                    continue

                executor = ExecutorAgent()
                res = executor.execute_order(intent)
                if res.get("status") == "executed":
                    await broadcast_log(
                        "ExecutorAgent",
                        f"Executed! {res['shares']:.6f} shares of {ticker} @ {res['price']}",
                        "success",
                    )
            else:
                await broadcast_log("RiskManager", decision.reason, "error")


async def exit_loop():
    """
    Laço RÁPIDO e independente do laço lento de entradas (P3-A Etapa 2):
    só releitura de posições ativas e gestão de stop/target, a cada
    EXIT_INTERVAL_SECONDS (~5s). Cada iteração roda isolada, mesmo padrão
    de resiliência do ai_committee_worker — uma falha pontual não mata o
    loop, só a próxima iteração é adiada.

    Heartbeat granular (P3-A Etapa 3): mark_exit_activity é chamado só no
    caminho de SUCESSO (iteração completou sem exceção — mesma convenção
    de mark_scan/ai_committee_worker), com o retorno de _run_exit_scan()
    indicando se a passada foi efetiva. Um "activity" batido mesmo em
    exceção mediria só "o laço tentou", não "o laço completou algo real".

    Supervisionado por exit_loop_supervisor() (P3-A Etapa 4) — se este
    loop morrer de vez (exceção escapando do try/except abaixo), o
    supervisor reinicia com backoff, isolado da contabilidade da entrada.
    """
    while True:
        try:
            effective = await _run_exit_scan()
            worker_state.state.mark_exit_activity(effective=effective)
        except asyncio.CancelledError:
            raise  # cancelamento limpo (shutdown/testes) deve propagar
        except Exception as e:
            logger.exception("Falha na iteração do exit_loop")
            await asyncio.to_thread(
                _alerta_telegram, f"⚠️ [Meridian] Falha na iteração do exit_loop: {e}"
            )
        await asyncio.sleep(worker_state.EXIT_INTERVAL_SECONDS)


async def ai_committee_worker():
    """
    Loop resiliente do comitê. Cada iteração roda isolada: uma falha pontual
    (ex.: schema inesperado do yfinance) é logada com stack trace + alerta
    Telegram e a iteração seguinte continua. O heartbeat (mark_scan) é gravado
    ANTES do sleep, para que um travamento dentro do próprio sleep também deixe
    o worker_alive stale após o timeout.
    """
    while True:
        try:
            await _run_one_scan_cycle()
            worker_state.state.mark_scan()
        except asyncio.CancelledError:
            raise  # cancelamento limpo (shutdown/testes) deve propagar
        except Exception as e:
            logger.exception("Falha na iteração do worker")
            await asyncio.to_thread(
                _alerta_telegram, f"⚠️ [Meridian] Falha na iteração do worker: {e}"
            )
        await asyncio.sleep(worker_state.SCAN_INTERVAL_SECONDS)


async def worker_supervisor():
    """
    Supervisiona ai_committee_worker(). Se o worker morrer de vez (exceção que
    escapa da guarda por iteração), loga, alerta no Telegram e reinicia com
    backoff exponencial. Esgotadas MAX_RESTARTS tentativas consecutivas, marca
    o estado como PARADO (nunca "online") e desiste.

    O contador de restart só zera por ESTABILIDADE (ver WorkerState.mark_scan):
    um worker que falha logo após cada ciclo não zera o contador e chega a
    PARADO, em vez de reiniciar para sempre.
    """
    while True:
        worker_state.state.on_worker_start()
        try:
            await ai_committee_worker()
            return  # saída normal (não ocorre — loop infinito)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Worker morreu de vez")
            worker_state.state.record_crash()
            rc = worker_state.state.restart_count
            if rc > worker_state.MAX_RESTARTS:
                worker_state.state.mark_stopped()
                await asyncio.to_thread(
                    _alerta_telegram,
                    "🛑 [Meridian] Worker PARADO — tentativas de restart esgotadas. "
                    "Intervenção manual necessária.",
                )
                return
            await asyncio.to_thread(
                _alerta_telegram,
                f"⚠️ [Meridian] Worker caiu (restart {rc}/{worker_state.MAX_RESTARTS}): {e}",
            )
            delay = min(2 ** (rc - 1), worker_state.BACKOFF_CAP_SECONDS)
            await asyncio.sleep(delay)


async def exit_loop_supervisor():
    """
    Supervisiona exit_loop() — P3-A Etapa 4. Mesmo padrão de
    worker_supervisor (restart com backoff exponencial), mas com
    contabilidade PRÓPRIA (worker_state.state.exit_supervision) — a saída
    esgotando os restarts não zera nem afeta o contador da entrada, e
    vice-versa. Reset por estabilidade usa SÓ STABLE_RESET_SECONDS pra
    este laço (Opção A da decisão de desenho): a 5s/ciclo, a métrica de
    ciclos usada pela entrada (calibrada pra 60s/ciclo) representaria só
    25s, tempo curto demais pra provar qualquer estabilidade de verdade.

    Ao esgotar MAX_RESTARTS:
    - Marca exit_supervision como "stopped" (mais severo dos 4 estados
      de /api/status — ver WorkerState._compute_status).
    - Ativa o bloqueio STICKY de novas entradas
      (set_exit_gate_sticky_block) — deliberadamente SEM caminho de
      auto-limpeza quando a saída volta a responder. Esgotar restarts
      significa algo estruturalmente quebrado; só reinício do processo
      (decisão explícita do operador) limpa o sticky.
    - Alerta com a LISTA de posições abertas (ticker, entrada, stop,
      alvo) — não um "algo grave aconteceu" genérico. Quando a proteção
      morre, saber QUAIS posições ficaram expostas é a informação
      acionável.
    """
    sup = worker_state.state.exit_supervision
    while True:
        sup.on_start()
        try:
            await exit_loop()
            return  # saída normal (não ocorre — loop infinito)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("exit_loop morreu de vez")
            sup.record_crash()
            rc = sup.restart_count
            if rc > worker_state.MAX_RESTARTS:
                sup.mark_stopped()
                worker_state.state.set_exit_gate_sticky_block()
                posicoes = _formatar_posicoes_abertas_para_alerta()
                await asyncio.to_thread(
                    _alerta_telegram,
                    "🛑 [Meridian] exit_loop PARADO — tentativas de restart "
                    "esgotadas. Novas entradas BLOQUEADAS até reinício manual "
                    f"do processo. Posições abertas SEM avaliação de stop:\n"
                    f"{posicoes}",
                )
                return
            await asyncio.to_thread(
                _alerta_telegram,
                f"⚠️ [Meridian] exit_loop caiu (restart {rc}/{worker_state.MAX_RESTARTS}): {e}",
            )
            delay = min(2 ** (rc - 1), worker_state.BACKOFF_CAP_SECONDS)
            await asyncio.sleep(delay)


def _log_if_supervisor_died(task: asyncio.Task) -> None:
    """Rede de segurança: loga se o próprio supervisor terminar inesperadamente."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.critical("Supervisor do worker terminou com exceção: %s", exc)
        worker_state.state.mark_stopped()
        _alerta_telegram(f"🛑 [Meridian] Supervisor do worker caiu: {exc}")


def _log_if_exit_supervisor_died(task: asyncio.Task) -> None:
    """Rede de segurança equivalente, pro exit_loop_supervisor (P3-A
    Etapa 4) — se o próprio SUPERVISOR (não o loop que ele supervisiona)
    terminar com exceção não tratada, isso é sério o bastante pra também
    ativar o bloqueio sticky de entradas, não só logar."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.critical("Supervisor do exit_loop terminou com exceção: %s", exc)
        worker_state.state.exit_supervision.mark_stopped()
        worker_state.state.set_exit_gate_sticky_block()
        _alerta_telegram(f"🛑 [Meridian] Supervisor do exit_loop caiu: {exc}")


def _enrich_trade_com_calculos(trade: dict) -> dict:
    """Calcula, no backend, os números que o frontend não pode calcular
    sozinho (honest-dashboard Bloco 2, CLAUDE.md: "no frontend, tudo que
    parece dado É dado vindo da API, ou não existe"):

    - alocado: capital em R$ comprometido na posição.
    - current_price: preço atual. Fechada = exit_price real, já
      conhecido. Ativa = derivado de entry_price + pnl_pct, o mesmo
      pnl_pct que o exit_loop mantém fresco a cada ~5s — não é uma nova
      fonte de dado, só move a mesma conta do navegador pro backend.
    - pnl_monetario: resultado em R$ (não só %).
    """
    entry_price = trade.get("entry_price") or 0.0
    shares = trade.get("shares") or 0.0
    pnl_pct = trade.get("pnl_pct") or 0.0
    side = trade.get("side")

    alocado = shares * entry_price

    if trade.get("status") == "closed" and trade.get("exit_price"):
        current_price = trade["exit_price"]
    elif side == "SELL":
        current_price = entry_price * (1 - pnl_pct / 100)
    else:
        current_price = entry_price * (1 + pnl_pct / 100)

    return {
        **trade,
        "alocado": alocado,
        "current_price": current_price,
        "pnl_monetario": alocado * (pnl_pct / 100),
    }


def _unavailable_portfolio_publication(pf: dict, reason: str, snapshot_id: Optional[str] = None) -> dict:
    """Publish no monetary field until immutable source evidence is available."""
    monetary_keys = (
        "patrimonio_total", "patrimonio_reservado", "saldo_disponivel",
        "em_posicoes", "saldo_livre", "margem_operavel", "saldo_operavel",
        "current_capital", "invested_capital", "initial_capital",
    )
    evidence = {
        "value": None, "verification_status": "unavailable", "reason": reason,
        "observed_at": None, "collected_at": None, "computed_at": None,
        "snapshot_id": snapshot_id,
    }
    return {
        **pf, **{key: None for key in monetary_keys}, **evidence,
        "metrics_provenance": {key: dict(evidence) for key in monetary_keys},
    }


@app.get("/api/positions")
def get_positions_route():
    from .data import database as db
    get_active_trades = db.get_active_trades
    get_closed_trades = db.get_closed_trades
    from trading_bot.data.valuation_snapshot import (
        get_latest_valuation_snapshot,
        is_snapshot_fresh,
        SnapshotIntegrityError,
    )

    def unpublished_trade(trade):
        # Identity/status remain visible; unverified financial values do not.
        fields = ("shares", "entry_price", "exit_price", "target_price", "stop_loss",
                  "current_price", "alocado", "pnl_monetario", "pnl_pct")
        return {**trade, **{key: None for key in fields},
                "verification_status": "unavailable",
                "reason": "immutable_trade_evidence_required"}

    capital = api_get_portfolio()
    try:
        snapshot = get_latest_valuation_snapshot(db_path=db.DB_PATH)
    except SnapshotIntegrityError:
        snapshot = None

    active_trades = get_active_trades()
    active_trade_ids = [t["id"] for t in active_trades if "id" in t]

    if (
        capital.get("verification_status") == "verified"
        and snapshot is not None
        and snapshot.is_valid
        and is_snapshot_fresh(snapshot, active_trade_ids)
    ):
        snap_items_by_trade_id = {it.trade_id: it for it in snapshot.active_positions}
        active = []
        for t in active_trades:
            trade_id = t.get("id")
            item = snap_items_by_trade_id.get(trade_id)
            if item and item.current_price is not None:
                active.append({
                    **t,
                    "shares": item.shares,
                    "entry_price": item.entry_price,
                    "current_price": item.current_price,
                    "alocado": item.alocado,
                    "pnl_monetario": item.pnl_monetario,
                    "pnl_pct": item.pnl_pct,
                    "verification_status": "verified",
                    "reason": None,
                    "snapshot_id": snapshot.snapshot_id,
                })
            else:
                active.append(unpublished_trade(t))
    else:
        active = [unpublished_trade(t) for t in active_trades]

    return {
        "capital": capital,
        "active_positions": active,
        "closed_positions": [unpublished_trade(t) for t in get_closed_trades()],
        "value": capital.get("value"),
        "verification_status": capital.get("verification_status"),
        "reason": capital.get("reason"),
    }


@app.post("/api/trades/{trade_id}/close")
def manual_close_trade(trade_id: int, api_key: str = Depends(verify_api_key)):

    from .data.database import get_trade_by_id

    row = get_trade_by_id(trade_id)

    if not row:
        raise HTTPException(status_code=404, detail="Trade não encontrado")

    ticker = row["ticker"]
    status = row["status"]
    if status != "active":
        raise HTTPException(status_code=400, detail="Trade não está ativo")

    from .data.feed import get_evidenced_quote
    quote = get_evidenced_quote(ticker)
    if quote is None:
        raise HTTPException(
            status_code=500,
            detail="Falha ao obter cotação evidenciada válida do ativo para encerramento manual (fail-closed)",
        )

    executor = ExecutorAgent()
    res = executor.close_order(
        trade_id, quote.price, "Encerrado manualmente pelo usuário", evidence=quote
    )

    if res.get("status") in ("error", "rejected"):
        raise HTTPException(status_code=500, detail=res.get("reason", "Erro ao fechar ordem."))

    return res


class TradeRequest(BaseModel):
    ticker: str
    side: str
    quantity: float


@app.post("/api/trades/execute")
def execute_manual_trade(req: TradeRequest, api_key: str = Depends(verify_api_key)):
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantidade deve ser maior que 0")

    # Ordem manual passa pelo mesmo PORTÃO ÚNICO do laço automático de
    # entradas (ver _avaliar_portao_de_entradas) — nunca um caminho de
    # bloqueio separado, que poderia divergir e deixar uma ordem manual
    # passar com a saída esgotada/sticky. asyncio.run() é seguro aqui: esta
    # rota é `def` (síncrona), então roda na threadpool do FastAPI, numa
    # thread sem event loop próprio.
    liberado, motivos = asyncio.run(_avaliar_portao_de_entradas())
    if not liberado:
        raise HTTPException(
            status_code=423,
            detail=f"Entradas bloqueadas (fail-closed): {', '.join(motivos)}",
        )

    from .data.database import get_portfolio

    current_price = get_current_price(req.ticker)
    if current_price <= 0:
        raise HTTPException(
            status_code=500, detail=f"Falha ao obter cotação para {req.ticker}"
        )

    # Validation logic (mocked logic through ExecutorAgent or direct)
    pf = get_portfolio()
    cost = current_price * req.quantity
    # usabilidade 2e: ordem manual respeita o mesmo capital OPERÁVEL do
    # laço automático (teto de margem incluído) — o executor re-checa o
    # teto dentro da transação de qualquer forma.
    if req.side == "BUY" and cost > pf.get("saldo_operavel", pf.get("saldo_livre", 0)):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Capital operável insuficiente. Necessário: R$ {cost:.2f}, "
                f"operável: R$ {pf.get('saldo_operavel', 0):.2f}"
            ),
        )

    # Explicit manual execution via ExecutorAgent using ManualExecutionIntent
    executor = ExecutorAgent()
    from .agents.contracts import ManualExecutionIntent

    target_price = (
        current_price * 1.05 if req.side == "BUY" else current_price * 0.95
    )
    stop_loss = (
        current_price * 0.98 if req.side == "BUY" else current_price * 1.02
    )
    allocated_capital = current_price * req.quantity
    intent = ManualExecutionIntent(
        ticker=req.ticker,
        side=req.side,
        entry_price=current_price,
        allocated_capital=allocated_capital,
        target_price=target_price,
        stop_loss=stop_loss,
        reason=f"Manual order via Boleta ({req.side} {req.quantity} @ {current_price})",
        operator="manual_operator",
    )

    res = executor.execute_manual_order(intent)

    if res.get("status") in ("error", "rejected"):
        raise HTTPException(status_code=400, detail=res.get("reason"))

    return res


class ValorRequest(BaseModel):
    valor: float


@app.post("/api/portfolio/depositar")
def api_depositar(req: ValorRequest, api_key: str = Depends(verify_api_key)):
    res = depositar_no_disponivel(req.valor)
    if not res["ok"]:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@app.post("/api/portfolio/retirar")
def api_retirar(req: ValorRequest, api_key: str = Depends(verify_api_key)):
    res = retirar_do_disponivel(req.valor)
    if not res["ok"]:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@app.post("/api/portfolio/margem_operavel")
def api_set_margem_operavel(req: ValorRequest, api_key: str = Depends(verify_api_key)):
    """usabilidade 2e: define o teto de exposição do bot. Validação
    (não-negativa, ≤ saldo_disponivel) mora em set_margem_operavel —
    fonte única, mesma usada pelos testes."""
    from .data.database import set_margem_operavel

    res = set_margem_operavel(req.valor)
    if not res["ok"]:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@app.get("/api/candles/{ticker}")
def get_candles(ticker: str):
    import math
    import pandas as pd
    from .data.feed import fetch_recent_data

    df = fetch_recent_data(ticker, period="30d", interval="1d")
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        raise HTTPException(status_code=503, detail={"code": "candle_history_unavailable"})

    # Check for duplicate column names or missing required columns
    required_cols = ["date", "open", "high", "low", "close", "volume"]
    cols = list(df.columns)
    if len(cols) != len(set(cols)):
        raise HTTPException(status_code=502, detail={"code": "invalid_candle_history"})
    if any(c not in cols for c in required_cols):
        raise HTTPException(status_code=502, detail={"code": "invalid_candle_history"})

    candles = []
    prev_dt = None

    for idx in range(len(df)):
        row = df.iloc[idx]
        raw_dt = row["date"]

        # Validate date
        if raw_dt is None or not isinstance(raw_dt, str) or len(raw_dt) != 10:
            raise HTTPException(status_code=502, detail={"code": "invalid_candle_history"})
        try:
            dt = pd.to_datetime(raw_dt, format="%Y-%m-%d", errors="raise")
        except Exception:
            raise HTTPException(status_code=502, detail={"code": "invalid_candle_history"})

        if prev_dt is not None and dt <= prev_dt:
            # Not strictly ascending or duplicate day
            raise HTTPException(status_code=502, detail={"code": "invalid_candle_history"})
        prev_dt = dt

        # Validate numeric OHLCV
        try:
            o_raw, h_raw, l_raw, c_raw, v_raw = row["open"], row["high"], row["low"], row["close"], row["volume"]
            if any(isinstance(x, (bool, str, pd.Series)) or x is None for x in (o_raw, h_raw, l_raw, c_raw, v_raw)):
                raise HTTPException(status_code=502, detail={"code": "invalid_candle_history"})

            o, h, l, c, v = float(o_raw), float(h_raw), float(l_raw), float(c_raw), float(v_raw)
            if any(math.isnan(x) or math.isinf(x) for x in (o, h, l, c, v)):
                raise HTTPException(status_code=502, detail={"code": "invalid_candle_history"})

            # Prices must be strictly positive, volume non-negative
            if o <= 0 or h <= 0 or l <= 0 or c <= 0 or v < 0:
                raise HTTPException(status_code=502, detail={"code": "invalid_candle_history"})

            # High and Low boundaries
            if not (l <= o <= h and l <= c <= h and l <= h):
                raise HTTPException(status_code=502, detail={"code": "invalid_candle_history"})
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=502, detail={"code": "invalid_candle_history"})

        candles.append(
            {
                "time": dt.strftime("%Y-%m-%d"),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "value": v,
            }
        )

    return {"ticker": ticker, "candles": candles}


from pydantic import BaseModel
from typing import Optional
import os

EMERGENCY_PASSWORD = os.environ.get("EMERGENCY_PASSWORD", "")


class ActionRequest(BaseModel):
    action: str
    password: Optional[str] = None


@app.post("/api/system/emergency_stop")
def system_emergency_stop(
    req: ActionRequest, api_key: str = Depends(verify_api_key)
):
    if not EMERGENCY_PASSWORD:
        # Fail-closed: rota mais destrutiva do arquivo (fecha TODAS as
        # posições). Sem senha configurada, nunca executar — 503, não 200.
        raise HTTPException(
            status_code=503,
            detail="Emergency password not configured on server.",
        )

    import hmac
    if not req.password or not hmac.compare_digest(req.password, EMERGENCY_PASSWORD):
        raise HTTPException(status_code=401, detail="Senha incorreta. Acesso negado.")

    try:
        from .data.database import get_active_trades
        active_trades = get_active_trades()

        executor = ExecutorAgent()
        closed_count = 0
        failed_count = 0
        failed_tickers = []

        from .data.feed import get_evidenced_quote

        for row in active_trades:
            trade_id = row["id"]
            ticker = row["ticker"]

            quote = None
            try:
                quote = get_evidenced_quote(ticker)
            except Exception:
                quote = None

            if quote is None:
                logger.warning(
                    "Emergency stop: cotação evidenciada indisponível para %s; posição não fechada (fail-closed).",
                    ticker,
                )
                failed_count += 1
                failed_tickers.append(ticker)
                continue

            try:
                res = executor.close_order(
                    trade_id, quote.price, "EMERGENCY STOP", evidence=quote
                )
            except Exception as exc:
                logger.exception(
                    "Emergency stop: executor close_order lançou exceção para trade %s (%s): %s",
                    trade_id, ticker, exc,
                )
                res = {"status": "exception", "reason": str(exc)}

            if res.get("status") == "closed":
                closed_count += 1
            else:
                logger.warning(
                    "Emergency stop: close_order rejeitado para trade %s (%s): %s",
                    trade_id, ticker, res.get("reason"),
                )
                failed_count += 1
                failed_tickers.append(ticker)

        total_trades = len(active_trades)
        if total_trades == 0:
            return {
                "status": "success",
                "success": True,
                "msg": "EMERGENCY STOP ACIONADO. Nenhuma posição ativa.",
                "total": 0,
                "closed": 0,
                "failed": 0,
            }

        all_closed = (failed_count == 0)
        status_str = "success" if all_closed else ("partial_failure" if closed_count > 0 else "failed")
        return {
            "status": status_str,
            "success": all_closed,
            "total": total_trades,
            "closed": closed_count,
            "failed": failed_count,
            "failed_tickers": failed_tickers,
            "msg": (
                f"EMERGENCY STOP ACIONADO. Todas as {closed_count} posições fechadas com sucesso."
                if all_closed
                else f"EMERGENCY STOP PARCIAL: {closed_count}/{total_trades} posições fechadas. {failed_count} falharam por ausência de cotação evidenciada válida."
            ),
        }
    except Exception as e:
        logger.error("Erro interno em emergency_stop: %s", e)
        return {"error": "Internal server error"}


@app.get("/api/elite/risk_metrics")
def get_risk_metrics_route():
    from .data.database import get_risk_metrics
    return get_risk_metrics(verify_provenance=True)


# WebSocket for real-time agent logs
active_connections = []


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        # Send an initial connection log
        await websocket.send_json(
            {"agent": "System", "msg": "Websocket connected to AI Core."}
        )
        while True:
            # Just keep connection open, or wait for incoming messages if needed
            _ = await websocket.receive_text()
    except Exception:
        pass
    finally:
        if websocket in active_connections:
            active_connections.remove(websocket)


async def broadcast_log(agent: str, msg: str, level: str = "info"):
    disconnected = []
    for ws in active_connections:
        try:
            await ws.send_json({"agent": agent, "msg": msg, "level": level})
        except Exception:
            disconnected.append(ws)

    for ws in disconnected:
        active_connections.remove(ws)

@app.get("/api/equity_snapshots")
def get_equity_snapshots_route():
    """honest-dashboard Bloco 3: espelha a tabela equity_snapshots, sem
    nenhum cálculo — a curva de patrimônio real do bot, um snapshot por
    dia de pregão (ver compute_current_equity/save_equity_snapshot)."""
    from .data.database import get_equity_snapshots

    return {"snapshots": get_equity_snapshots()}


@app.get("/api/broker/status")
def get_broker_status_route():
    """Track B, Commit 1: só confirma presença de CEDRO_API_KEY no
    ambiente -- nunca o valor. Substitui o has_cedro_key hardcoded em
    false que existia só no frontend (App.jsx), sem nenhum consumidor
    real no backend."""
    return {"has_cedro_key": bool(os.environ.get("CEDRO_API_KEY"))}


@app.get("/api/portfolio")
def api_get_portfolio():
    from .data import database as db
    from trading_bot.data.valuation_snapshot import (
        get_latest_valuation_snapshot,
        create_valuation_snapshot,
        is_snapshot_fresh,
        SnapshotIntegrityError,
    )
    from backend.app.data.feed import get_evidenced_quote

    pf = db.get_portfolio()
    active_trades = db.get_active_trades()
    active_trade_ids = [t["id"] for t in active_trades if "id" in t]

    try:
        snapshot = get_latest_valuation_snapshot(db_path=db.DB_PATH)
    except SnapshotIntegrityError as e:
        return _unavailable_portfolio_publication(pf, f"snapshot_integrity_error: {str(e)}")

    if snapshot is None or not is_snapshot_fresh(snapshot, active_trade_ids):
        try:
            snapshot = create_valuation_snapshot(
                db_path=db.DB_PATH,
                quote_provider=get_evidenced_quote,
            )
        except SnapshotIntegrityError as e:
            return _unavailable_portfolio_publication(pf, f"snapshot_integrity_error: {str(e)}")

    if not snapshot.is_valid or snapshot.equity is None:
        if "feed_price_unavailable" in (snapshot.reason or ""):
            reason = "feed_price_unavailable"
        elif (
            "quote_evidence_required" in (snapshot.reason or "")
            or "immutable" in (snapshot.reason or "")
            or "stale_quote" in (snapshot.reason or "")
            or "future_quote" in (snapshot.reason or "")
        ):
            reason = "immutable_valuation_evidence_required"
        else:
            reason = snapshot.reason or "immutable_valuation_evidence_required"
        return _unavailable_portfolio_publication(pf, reason, snapshot_id=snapshot.snapshot_id)

    # Evaluate snapshot through deterministic provenance gate
    prov_agent = db.get_metric_provenance_agent()
    resolved_db = Path(db.DB_PATH)
    snapshot_dir = resolved_db.parent / "snapshots"
    snapshot_path = snapshot_dir / f"valuation_{snapshot.snapshot_id}.json"
    if not snapshot_path.exists():
        snapshot_path = db.PROJECT_ROOT / "data" / "snapshots" / f"valuation_{snapshot.snapshot_id}.json"

    if not snapshot_path.exists():
        return _unavailable_portfolio_publication(
            pf, "immutable_valuation_evidence_required", snapshot_id=snapshot.snapshot_id
        )

    try:
        source_ref = str(snapshot_path.resolve().relative_to(db.PROJECT_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        source_ref = f"data/snapshots/valuation_{snapshot.snapshot_id}.json"

    import hashlib
    source_sha256 = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()

    monetary_keys = (
        "patrimonio_total", "patrimonio_reservado", "saldo_disponivel",
        "em_posicoes", "saldo_livre", "margem_operavel", "saldo_operavel",
        "current_capital", "invested_capital", "initial_capital",
    )

    # Derive saldo_operavel strictly from frozen snapshot fields using Meridian domain rule
    snap_saldo_livre = snapshot.portfolio.saldo_livre
    snap_margem_operavel = snapshot.portfolio.margem_operavel
    snap_em_posicoes = snapshot.portfolio.em_posicoes

    if snap_margem_operavel is None:
        derived_saldo_operavel = snap_saldo_livre
    else:
        derived_saldo_operavel = round(
            min(snap_saldo_livre, max(0.0, snap_margem_operavel - snap_em_posicoes)), 4
        )

    candidate_values = {
        "patrimonio_total": snapshot.equity,
        "saldo_disponivel": snapshot.portfolio.saldo_disponivel,
        "em_posicoes": snapshot.portfolio.em_posicoes,
        "saldo_livre": snapshot.portfolio.saldo_livre,
        "margem_operavel": snapshot.portfolio.margem_operavel,
        "saldo_operavel": derived_saldo_operavel,
        "patrimonio_reservado": None,
        "current_capital": None,
        "invested_capital": None,
        "initial_capital": None,
    }

    metrics_provenance = {}
    published_monetary = {}

    for metric_name in monetary_keys:
        val = candidate_values.get(metric_name)
        if val is None:
            metrics_provenance[metric_name] = {
                "value": None,
                "verification_status": "unavailable",
                "reason": "metric_value_none",
                "snapshot_id": snapshot.snapshot_id,
            }
            published_monetary[metric_name] = None
            continue

        record_payload = {
            "metric_name": metric_name,
            "value": float(val),
            "unit": "currency_brl",
            "source_ref": source_ref,
            "source_sha256": source_sha256,
            "observed_at": snapshot.observed_at,
            "collected_at": snapshot.collected_at,
            "computed_at": snapshot.computed_at,
            "owner": "trading_bot.data.valuation_snapshot",
            "method_version": "1.0",
        }
        eval_res = prov_agent.evaluate(record_payload)
        eval_res["snapshot_id"] = snapshot.snapshot_id
        if eval_res.get("verification_status") == "verified":
            published_monetary[metric_name] = float(val)
        else:
            published_monetary[metric_name] = None
            eval_res["observed_at"] = None
            eval_res["collected_at"] = None
            eval_res["computed_at"] = None
        metrics_provenance[metric_name] = eval_res

    patrimonio_eval = metrics_provenance.get("patrimonio_total", {})
    is_patrimonio_verified = (patrimonio_eval.get("verification_status") == "verified")
    overall_status = "verified" if is_patrimonio_verified else "unavailable"
    overall_reason = None if is_patrimonio_verified else patrimonio_eval.get("reason", "independent_approval_required")

    return {
        **pf,
        **published_monetary,
        "value": published_monetary.get("patrimonio_total"),
        "verification_status": overall_status,
        "reason": overall_reason,
        "snapshot_id": snapshot.snapshot_id,
        "observed_at": snapshot.observed_at.isoformat() if is_patrimonio_verified else None,
        "collected_at": snapshot.collected_at.isoformat() if is_patrimonio_verified else None,
        "computed_at": snapshot.computed_at.isoformat() if is_patrimonio_verified else None,
        "metrics_provenance": metrics_provenance,
    }

@app.get("/api/trades/active")
def api_get_active_trades():
    from .data.database import get_active_trades
    return get_active_trades()

@app.get("/api/trades/closed")
def api_get_closed_trades():
    from .data.database import get_closed_trades
    return get_closed_trades()
