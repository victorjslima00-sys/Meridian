from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import random
from typing import Dict, Any

app = FastAPI(title="Meridian AI Core")

import os

ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:5173"  # dev local
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
        "active_agents": 3
    }

from .data.database import get_portfolio, get_trades, init_db
from .data.feed import get_current_price
from .agents.market_analyst import MarketAnalyst
from .agents.risk_manager import RiskManager
from .agents.executor import ExecutorAgent

async def ai_committee_worker():
    """
    Continuous loop that runs the AI Committee every 60 seconds.
    """
    tickers_to_watch = ["BTC-USD", "ETH-USD", "SOL-USD"]
    
    while True:
        await asyncio.sleep(5) # start 5s after boot
        print("Starting AI committee scan loop...", flush=True)
        for ticker in tickers_to_watch:
            print(f"Scanning {ticker}...", flush=True)
            
            # Use data feed to get the latest price directly for evaluation
            from .data.feed import fetch_recent_data
            df_recent = fetch_recent_data(ticker, period="1d", interval="15m")
            if df_recent is None or len(df_recent) == 0:
                continue
            current_price = df_recent.iloc[-1]['close']

            # Database connection
            import sqlite3
            from .data.database import DB_PATH
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # --- PHASE 1: EXIT LOOP (Manage Open Positions) ---
            cursor.execute("SELECT id, side, target_price, stop_loss FROM trades WHERE ticker = ? AND status = 'active'", (ticker,))
            active_trade = cursor.fetchone()
            
            if active_trade:
                trade_id, side, target_price, stop_loss = active_trade
                
                close_trade = False
                close_reason = ""
                
                # Basic Stop Loss / Take Profit Logic
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
                        
                if close_trade:
                    await broadcast_log("System", f"Closing active trade on {ticker}: {close_reason}", "warning")
                    executor = ExecutorAgent()
                    res = executor.close_order(trade_id, current_price, close_reason)
                    await broadcast_log("ExecutorAgent", f"Closed trade! PnL: {res.get('pnl_pct', 0.0):.2f}%", "success")
                else:
                    await broadcast_log("System", f"{ticker} já possui posição aberta. Monitorando (Current: {current_price})...", "info")
                
                conn.close()
                continue
            conn.close()
                
            # --- PHASE 2: ENTRY LOOP (Find New Opportunities) ---
            await broadcast_log("System", f"Scanning {ticker} for entry...", "info")
            await asyncio.sleep(2)
            
            # 1. Analyst (now uses Gemini async)
            analyst = MarketAnalyst(ticker)
            analysis = await analyst.analyze()
            await broadcast_log("MarketAnalyst", f"{ticker} Analysis: {analysis['signal']} - {analysis['reason']}", "info")
            await asyncio.sleep(2)
            
            # 2. Risk Manager
            if analysis['signal'] != "HOLD":
                await broadcast_log("RiskManager", f"Evaluating {analysis['signal']} on {ticker}...", "warning")
                pf = get_portfolio()
                # GAP 4 Fix: Don't default to 10000.0, use actual DB value
                current_capital = pf.get('current_capital', 0.0)
                
                rm = RiskManager(current_capital=current_capital)
                decision = rm.evaluate_trade(analysis)
                await asyncio.sleep(2)
                
                if decision['approved']:
                    await broadcast_log("RiskManager", decision['reason'], "success")
                    await asyncio.sleep(1)
                    
                    # 3. Executor
                    executor = ExecutorAgent()
                    res = executor.execute_order(ticker, decision, analysis)
                    if res['status'] == 'executed':
                        await broadcast_log("ExecutorAgent", f"Executed! {res['shares']:.0f} shares of {ticker} @ {res['price']}", "success")
                else:
                    await broadcast_log("RiskManager", decision['reason'], "error")
            
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
    cursor.execute("SELECT * FROM trades WHERE status = 'active' OR status = 'closed'")
    rows = cursor.fetchall()
    
    active_positions = []
    for r in rows:
        active_positions.append(dict(r))
    conn.close()
    
    return {
        "capital": {
            "initial": pf.get('initial_capital', 10000.0),
            "current": pf.get('current_capital', 10500.0),
            "invested": pf.get('invested_capital', 1200.0)
        },
        "active_positions": active_positions
    }

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
        dt = pd.to_datetime(row['date'])
        # Fix yfinance bug where current day has 0 for Open/High/Low
        o = float(row['open'])
        h = float(row['high'])
        l = float(row['low'])
        c = float(row['close'])
        if o == 0 and h == 0 and l == 0 and c > 0:
            o = c
            h = c
            l = c
            
        candles.append({
            "time": dt.strftime('%Y-%m-%d'),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "value": float(row.get('volume', 0))
        })
    return {"ticker": ticker, "candles": candles}

@app.get("/api/ecosystem")
def get_ecosystem():
    return {
        "agents": [
            {"id": "market_analyst", "name": "Analista de Mercado", "status": "online"},
            {"id": "risk_manager", "name": "Gerenciador de Risco", "status": "online"},
            {"id": "executor", "name": "Executor", "status": "online"}
        ],
        "system_latency": "12ms"
    }

@app.get("/api/market_tape")
def get_tape():
    return {
        "tape": [
            "PETR4 36.50 ▲ 1.2%",
            "VALE3 61.20 ▼ 0.5%",
            "ITUB4 34.10 ▲ 0.8%",
            "BBDC4 12.45 ▼ 1.1%",
            "BBAS3 28.90 ▲ 0.3%"
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
        import sqlite3
        from .data.database import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE trades SET status = 'CANCELLED' WHERE status = 'active'")
        conn.commit()
        conn.close()
        return {"status": "success", "msg": "EMERGENCY STOP ACIONADO. Todas as posições fechadas."}
    except Exception as e:
        return {"error": "Internal server error"}

@app.get('/api/elite/risk_metrics')
def get_risk_metrics():
    # Retorna métricas hardcoded temporárias, simulando os resultados dos backtests em settings
    return {
        'sharpe': 0.87,
        'sortino': 1.12,
        'calmar': 0.65,
        'max_drawdown_pct': -8.3,
        'var_95_daily': -9.40,
        'win_rate': 0.41,
        'avg_win': 3.2,
        'avg_loss': -1.8
    }

# WebSocket for real-time agent logs
active_connections = []

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        # Send an initial connection log
        await websocket.send_json({"agent": "System", "msg": "Websocket connected to AI Core."})
        while True:
            # Just keep connection open, or wait for incoming messages if needed
            data = await websocket.receive_text()
    except Exception:
        active_connections.remove(websocket)

async def broadcast_log(agent: str, msg: str, level: str = "info"):
    disconnected = []
    for ws in active_connections:
        try:
            await ws.send_json({"agent": agent, "msg": msg, "level": level})
        except:
            disconnected.append(ws)
    
    for ws in disconnected:
        active_connections.remove(ws)
