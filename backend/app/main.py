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

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
def get_status():
    return {
        "status": "online",
        "mode": "paper_trading",
        "uptime": "99.9%",
        "active_agents": 3,
    }


import sqlite3
from .data.database import (
    get_portfolio,
    get_trades,
    init_db,
    depositar_no_disponivel,
    retirar_do_disponivel,
    DB_PATH,
)

from .agents.market_analyst import MarketAnalyst
from .agents.risk_manager import RiskManager
from .agents.executor import ExecutorAgent


async def ai_committee_worker():
    """
    Continuous loop that runs the AI Committee every 60 seconds.
    """
    tickers_to_watch = ["BTC-USD", "ETH-USD", "SOL-USD"]

    while True:
        await asyncio.sleep(5)  # start 5s after boot
        print("Starting AI committee scan loop...", flush=True)
        for ticker in tickers_to_watch:
            print(f"Scanning {ticker}...", flush=True)

            # Use data feed to get the latest price directly for evaluation
            from .data.feed import fetch_recent_data

            df_recent = fetch_recent_data(ticker, period="1d", interval="15m")
            if df_recent is None or len(df_recent) == 0:
                continue
            current_price = df_recent.iloc[-1]["close"]

            # Database connection
            conn = sqlite3.connect(DB_PATH)
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
                _conn = sqlite3.connect(DB_PATH)
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

    # Fetch active trades directly from db
    import sqlite3
    from .data.database import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM trades WHERE status = 'active'")
    active_rows = cursor.fetchall()
    active_positions = [dict(r) for r in active_rows]

    cursor.execute(
        "SELECT * FROM trades WHERE status = 'closed' ORDER BY exit_date DESC"
    )
    closed_rows = cursor.fetchall()
    closed_positions = [dict(r) for r in closed_rows]

    conn.close()

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
def manual_close_trade(trade_id: int):

    import sqlite3
    from .data.database import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT ticker, status FROM trades WHERE id = ?", (trade_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Trade não encontrado")

    ticker, status = row
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
def execute_manual_trade(req: TradeRequest):
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantidade deve ser maior que 0")

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
def api_depositar(req: ValorRequest):
    res = depositar_no_disponivel(req.valor)
    if not res["ok"]:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@app.post("/api/portfolio/retirar")
def api_retirar(req: ValorRequest):
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
    if req.password != EMERGENCY_PASSWORD:
        return {"error": "Senha incorreta. Acesso negado."}

    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, entry_price FROM trades WHERE status = 'active'")
            active_trades = cursor.fetchall()

            executor = ExecutorAgent()
            for row in active_trades:
                trade_id, entry_price = row
                executor.close_order(trade_id, entry_price, "EMERGENCY STOP")
        finally:
            conn.close()
        return {
            "status": "success",
            "msg": "EMERGENCY STOP ACIONADO. Todas as posições fechadas.",
        }
    except Exception:
        return {"error": "Internal server error"}


@app.get("/api/elite/risk_metrics")
def get_risk_metrics():
    # Retorna métricas hardcoded temporárias, simulando os resultados dos backtests em settings
    return {
        "sharpe": 0.87,
        "sortino": 1.12,
        "calmar": 0.65,
        "max_drawdown_pct": -8.3,
        "var_95_daily": -9.40,
        "win_rate": 0.41,
        "avg_win": 3.2,
        "avg_loss": -1.8,
    }


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
