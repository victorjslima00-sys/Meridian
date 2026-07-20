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
        "active_agents": 3,
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
    hoje_b3,
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
from typing import Optional


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


def _price_is_trustworthy(price, open_=None, high=None, low=None) -> bool:
    """FAIL-CLOSED para decisões de saída: um preço não confiável nunca deve
    disparar (nem impedir) o fechamento de uma posição por engano. A decisão
    certa diante de dado ruim é NÃO decidir nada — manter a posição como
    está, nunca 'vender por precaução'.

    Rejeita: None, não numérico, <= 0, NaN — e o artefato conhecido do
    yfinance de o candle do dia corrente vir com Open/High/Low zerados (ver
    também o patch cosmético em get_candles). Mesmo com um close que pareça
    válido, um candle com O/H/L zerados é sinal de dado incompleto — não
    confiável o bastante para decidir um stop-loss/take-profit.
    """
    if price is None:
        return False
    try:
        price = float(price)
    except (TypeError, ValueError):
        return False
    if math.isnan(price) or price <= 0:
        return False

    if open_ is not None and high is not None and low is not None:
        try:
            o, h, low_ = float(open_), float(high), float(low)
        except (TypeError, ValueError):
            return False
        if o == 0 and h == 0 and low_ == 0:
            return False

    return True


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

    for ticker in active_tickers:
        from .data.feed import fetch_recent_data

        df_recent = await asyncio.to_thread(
            fetch_recent_data, ticker, period="1d", interval="15m",
            ttl=worker_state.exit_price_cache_ttl_seconds(),
        )
        if df_recent is None or len(df_recent) == 0:
            # Falha total do fetch (ex.: rate limit esgotando os retries) —
            # este ticker ficou sem avaliação nesta passada. Mesma
            # categoria de "não efetivo" que preço não confiável abaixo.
            all_trustworthy = False
            continue

        last_row = df_recent.iloc[-1]
        current_price = last_row["close"]

        if not _price_is_trustworthy(
            current_price,
            open_=last_row.get("open"),
            high=last_row.get("high"),
            low=last_row.get("low"),
        ):
            logger.warning(
                "Exit scan: preço não confiável para %s (%r) — mantendo "
                "posição, nenhuma ação tomada.", ticker, current_price
            )
            # Log sempre acontece (barato); o Telegram é deduplicado —
            # exit_loop roda a cada poucos segundos, e uma condição
            # persistente não pode virar um alerta a cada iteração.
            if _should_alert_price_untrustworthy(ticker, "untrustworthy_price"):
                await asyncio.to_thread(
                    _alerta_telegram,
                    f"⚠️ [Meridian] Exit scan: preço não confiável para {ticker} "
                    f"({current_price!r}) — posição mantida (fail-closed).",
                )
            all_trustworthy = False
            continue

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
                "UPDATE trades SET pnl_pct = ? WHERE id = ?",
                (live_pnl_pct, trade_id),
            )
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
                        "UPDATE trades SET stop_loss = ? WHERE id = ?",
                        (entry_price, trade_id),
                    )
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
                        "UPDATE trades SET stop_loss = ? WHERE id = ?",
                        (entry_price, trade_id),
                    )
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
            res = executor.close_order(trade_id, current_price, close_reason)
            await broadcast_log(
                "ExecutorAgent",
                f"Closed trade! PnL: {res.get('pnl_pct', 0.0):.2f}%",
                "success",
            )
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
        raw_tickers = cfg.get("_universe", "tickers", default=["PETR4", "VALE3", "ITUB4"])
        tickers_to_watch = [f"{t}.SA" if not t.endswith(".SA") else t for t in raw_tickers]
    except Exception:
        tickers_to_watch = ["PETR4.SA", "VALE3.SA"]

    # Snapshot diário de equity (data do pregão B3) — base do circuit breaker
    try:
        hoje = hoje_b3()
        if not has_snapshot_for(hoje):
            equity = await asyncio.to_thread(compute_current_equity)
            save_equity_snapshot(hoje, equity)
            await broadcast_log(
                "System", f"Equity snapshot {hoje}: R$ {equity:.2f}", "info"
            )
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
        from .runtime_config import RuntimeConfig
        runtime = RuntimeConfig.load()
        if not entradas_liberadas or not runtime.autonomous_entries_enabled:
            continue
        await broadcast_log("System", f"Scanning {ticker} for entry...", "info")

        # 1. Analyst (now uses Gemini async)
        analyst = MarketAnalyst(ticker)
        analysis = await analyst.analyze()
        await broadcast_log(
            "MarketAnalyst",
            f"{ticker} Analysis: {analysis['signal']} - {analysis['reason']}",
            "info",
        )

        # 2. Risk Manager (com checagem de correlação)
        if analysis["signal"] != "HOLD":
            await broadcast_log(
                "RiskManager",
                f"Evaluating {analysis['signal']} on {ticker}...",
                "warning",
            )
            pf = get_portfolio()
            saldo_livre = pf.get("saldo_livre", 0.0)

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

            rm = RiskManager(saldo_livre=saldo_livre)
            decision = rm.evaluate_trade(
                analysis, ticker=ticker, open_tickers=open_tickers
            )

            if decision["approved"]:
                await broadcast_log("RiskManager", decision["reason"], "success")

                # 3. Executor
                executor = ExecutorAgent()
                res = executor.execute_order(ticker, decision, analysis)
                if res["status"] == "executed":
                    await broadcast_log(
                        "ExecutorAgent",
                        f"Executed! {res['shares']:.6f} shares of {ticker} @ {res['price']}",
                        "success",
                    )
            else:
                await broadcast_log("RiskManager", decision["reason"], "error")


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


@app.get("/api/positions")
def get_positions_route():
    pf = get_portfolio()

    from .data.database import get_active_trades, get_closed_trades

    active_positions = [_enrich_trade_com_calculos(t) for t in get_active_trades()]
    closed_positions = [_enrich_trade_com_calculos(t) for t in get_closed_trades()]

    return {
        "capital": {
            "patrimonio_total": pf.get("patrimonio_total", 0.0),
            "saldo_disponivel": pf.get("saldo_disponivel", 100.0),
            "em_posicoes": pf.get("em_posicoes", 0.0),
            "saldo_livre": pf.get("saldo_livre", 100.0),
        },
        "active_positions": active_positions,
        "closed_positions": closed_positions,
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

    current_price = get_current_price(ticker)
    if current_price <= 0:
        raise HTTPException(
            status_code=500, detail="Falha ao obter preço atual do ativo"
        )

    executor = ExecutorAgent()
    res = executor.close_order(
        trade_id, current_price, "Encerrado manualmente pelo usuário"
    )

    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("reason"))

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
    if req.side == "BUY" and cost > pf.get("saldo_livre", 0):
        raise HTTPException(
            status_code=400,
            detail=f"Saldo livre insuficiente. Necessário: R$ {cost:.2f}",
        )

    # Simple execution via ExecutorAgent
    executor = ExecutorAgent()

    # We create a mock decision dictionary that executor expects
    decision = {
        "approved": True,
        "reason": "Ordem manual enviada via Boleta (Scalper)",
        "confidence": 1.0,
        "target_price": (
            current_price * 1.05 if req.side == "BUY" else current_price * 0.95
        ),
        "stop_loss": (
            current_price * 0.98 if req.side == "BUY" else current_price * 1.02
        ),
        "allocated_capital": current_price * req.quantity,
        "side": req.side,
    }

    analysis = {
        "signal": req.side,
        "reason": "Manual Execution",
        "last_price": current_price,
    }

    res = executor.execute_order(req.ticker, decision, analysis)

    if res.get("status") == "error":
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


@app.get("/api/candles/{ticker}")
def get_candles(ticker: str):
    from .data.feed import fetch_recent_data

    df = fetch_recent_data(ticker, period="30d", interval="1d")
    if df is None:
        return {"ticker": ticker, "candles": []}

    # Format for lightweight-charts
    candles = []
    import pandas as pd

    for idx, row in df.iterrows():
        # timestamp to YYYY-MM-DD
        dt = pd.to_datetime(row["date"])
        # Fix yfinance bug where current day has 0 for Open/High/Low
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        if o == 0 and h == 0 and l == 0 and c > 0:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"Patching broken yfinance data for {ticker} on {dt.strftime('%Y-%m-%d')}: replacing zeroed O/H/L with Close ({c})")
            o = c
            h = c
            l = c

        candles.append(
            {
                "time": dt.strftime("%Y-%m-%d"),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "value": float(row.get("volume", 0)),
            }
        )
    return {"ticker": ticker, "candles": candles}


@app.get("/api/ecosystem")
def get_ecosystem():
    return {
        "agents": [
            {"id": "market_analyst", "name": "Analista de Mercado", "status": "online"},
            {"id": "risk_manager", "name": "Gerenciador de Risco", "status": "online"},
            {"id": "executor", "name": "Executor", "status": "online"},
        ],
        "system_latency": "12ms",
    }


@app.get("/api/market_tape")
def get_tape():
    return {
        "tape": [
            "PETR4 36.50 ▲ 1.2%",
            "VALE3 61.20 ▼ 0.5%",
            "ITUB4 34.10 ▲ 0.8%",
            "BBDC4 12.45 ▼ 1.1%",
            "BBAS3 28.90 ▲ 0.3%",
        ]
    }


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
        for row in active_trades:
            trade_id = row["id"]
            ticker = row["ticker"]
            entry_price = row["entry_price"]
            
            from .data.feed import get_current_price
            current_price = get_current_price(ticker)
            if current_price <= 0:
                current_price = entry_price # fallback to entry if feed is down
                
            executor.close_order(trade_id, current_price, "EMERGENCY STOP")
        return {
            "status": "success",
            "msg": "EMERGENCY STOP ACIONADO. Todas as posições fechadas.",
        }
    except Exception:
        return {"error": "Internal server error"}


@app.get("/api/elite/risk_metrics")
def get_risk_metrics_route():
    from .data.database import get_risk_metrics
    return get_risk_metrics()


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

@app.get("/api/portfolio")
def api_get_portfolio():
    from .data.database import get_portfolio
    return get_portfolio()

@app.get("/api/trades/active")
def api_get_active_trades():
    from .data.database import get_active_trades
    return get_active_trades()

@app.get("/api/trades/closed")
def api_get_closed_trades():
    from .data.database import get_closed_trades
    return get_closed_trades()
