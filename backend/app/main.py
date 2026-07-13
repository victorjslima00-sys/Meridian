from .data.feed import get_current_price
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import random
from pydantic import BaseModel

app = FastAPI(title="Meridian AI Core")

import os

ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173"  # dev local
).split(",")

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader
import hmac

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.environ.get("API_KEY", "MERIDIAN_DEV_KEY")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

def verify_api_key(api_key: str = Security(api_key_header)):
    if not hmac.compare_digest(api_key, API_KEY):
        raise HTTPException(
            status_code=403,
            detail="Could not validate credentials",
        )
    return api_key


@app.get("/api/status")
def get_status():
    return {
        "status": "online",
        "mode": "paper_trading",
        "uptime": "99.9%",
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


async def ai_committee_worker():
    """
    Continuous loop that runs the AI Committee every 60 seconds.
    """
    try:
        from trading_bot.core.config import AppConfig
        cfg = AppConfig.load()
        raw_tickers = cfg.get("_universe", "tickers", default=["PETR4", "VALE3", "ITUB4"])
        tickers_to_watch = [f"{t}.SA" if not t.endswith(".SA") else t for t in raw_tickers]
    except Exception:
        tickers_to_watch = ["PETR4.SA", "VALE3.SA"]

    while True:
        await asyncio.sleep(5)  # start 5s after boot
        print("Starting AI committee scan loop...", flush=True)

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

        # Circuit breaker: avaliado 1x por ciclo. FAIL-CLOSED: erro = bloqueia
        # novas entradas; a fase de saída (Phase 1) roda sempre.
        try:
            from trading_bot.risk.circuit_breaker import CircuitBreaker
            entradas_liberadas = await asyncio.to_thread(
                CircuitBreaker.from_config().can_trade
            )
        except Exception as e:
            logger.error(f"Circuit breaker indisponível ({e}) — bloqueando entradas.")
            entradas_liberadas = False
        if not entradas_liberadas:
            await broadcast_log(
                "System",
                "Circuit breaker ativo: novas entradas bloqueadas (gestão de saídas segue normal).",
                "warning",
            )

        for ticker in tickers_to_watch:
            print(f"Scanning {ticker}...", flush=True)

            # Use data feed to get the latest price directly for evaluation
            from .data.feed import fetch_recent_data

            df_recent = await asyncio.to_thread(fetch_recent_data, ticker, period="1d", interval="15m")
            if df_recent is None or len(df_recent) == 0:
                continue
            current_price = df_recent.iloc[-1]["close"]

            # Database connection
            from .data.database import get_connection
            conn = get_connection()
            try:
                cursor = conn.cursor()

                # --- PHASE 1: EXIT LOOP (Manage Open Positions) ---
                cursor.execute(
                    "SELECT id, side, entry_price, target_price, stop_loss FROM trades WHERE ticker = ? AND status = 'active'",
                    (ticker,),
                )
                active_trade = cursor.fetchone()

                if active_trade:
                    trade_id, side, entry_price, target_price, stop_loss = active_trade

                    close_trade = False
                    close_reason = ""

                    # Update live PnL in the database so the frontend can display it
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

                    # Breakeven Logic (50% to target)
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

                    # Basic Stop Loss / Take Profit Logic
                    if side == "BUY":
                        if target_price > 0 and current_price >= target_price:
                            close_trade, close_reason = (
                                True,
                                f"Take Profit hit at {current_price}",
                            )
                        elif stop_loss > 0 and current_price <= stop_loss:
                            close_trade, close_reason = (
                                True,
                                f"Stop Loss hit at {current_price}",
                            )
                    elif side == "SELL":
                        if target_price > 0 and current_price <= target_price:
                            close_trade, close_reason = (
                                True,
                                f"Take Profit hit at {current_price}",
                            )
                        elif stop_loss > 0 and current_price >= stop_loss:
                            close_trade, close_reason = (
                                True,
                                f"Stop Loss hit at {current_price}",
                            )

                    if close_trade:
                        await broadcast_log(
                            "System",
                            f"Closing active trade on {ticker}: {close_reason}",
                            "warning",
                        )
                        executor = ExecutorAgent()
                        res = executor.close_order(
                            trade_id, current_price, close_reason
                        )
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

                    continue
            finally:
                conn.close()

            # --- PHASE 2: ENTRY LOOP (Find New Opportunities) ---
            if not entradas_liberadas:
                continue
            await broadcast_log("System", f"Scanning {ticker} for entry...", "info")
            await asyncio.sleep(2)

            # 1. Analyst (now uses Gemini async)
            analyst = MarketAnalyst(ticker)
            analysis = await analyst.analyze()
            await broadcast_log(
                "MarketAnalyst",
                f"{ticker} Analysis: {analysis['signal']} - {analysis['reason']}",
                "info",
            )
            await asyncio.sleep(2)

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
                await asyncio.sleep(2)

                if decision["approved"]:
                    await broadcast_log("RiskManager", decision["reason"], "success")
                    await asyncio.sleep(1)

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

        await asyncio.sleep(60)


@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(ai_committee_worker())


@app.get("/api/positions")
def get_positions_route():
    pf = get_portfolio()

    from .data.database import get_active_trades, get_closed_trades

    active_positions = get_active_trades()
    closed_positions = get_closed_trades()

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

    # Entrada nova também respeita o circuit breaker (FAIL-CLOSED)
    try:
        from trading_bot.risk.circuit_breaker import CircuitBreaker
        entradas_liberadas = CircuitBreaker.from_config().can_trade()
    except Exception as e:
        logger.error(f"Circuit breaker indisponível ({e}) — bloqueando entrada manual.")
        entradas_liberadas = False
    if not entradas_liberadas:
        raise HTTPException(
            status_code=423,
            detail="Circuit breaker ativo: novas entradas bloqueadas (fail-closed).",
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
def system_emergency_stop(req: ActionRequest):
    if not EMERGENCY_PASSWORD:
        return {"error": "Emergency password not configured on server."}
    
    import hmac
    if not hmac.compare_digest(req.password, EMERGENCY_PASSWORD):
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
