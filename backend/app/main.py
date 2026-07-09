from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import random
from typing import Dict, Any

app = FastAPI(title="Meridian AI Core")

# CORS config to allow the React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For dev, allow all
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
            
            # Check if we already have an active position for this ticker
            import sqlite3
            from .data.database import DB_PATH
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM trades WHERE ticker = ? AND status = 'active'", (ticker,))
            is_active = cursor.fetchone()[0] > 0
            conn.close()
            
            if is_active:
                await broadcast_log("System", f"{ticker} já possui posição aberta. Pulando scan...", "info")
                continue
                
            await broadcast_log("System", f"Scanning {ticker}...", "info")
            await asyncio.sleep(2)
            
            # 1. Analyst
            analyst = MarketAnalyst(ticker)
            analysis = analyst.analyze()
            await broadcast_log("MarketAnalyst", f"{ticker} Analysis: {analysis['signal']} - {analysis['reason']}", "info")
            await asyncio.sleep(2)
            
            # 2. Risk Manager
            if analysis['signal'] != "HOLD":
                await broadcast_log("RiskManager", f"Evaluating {analysis['signal']} on {ticker}...", "warning")
                pf = get_portfolio()
                rm = RiskManager(current_capital=pf.get('current_capital', 10000.0))
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

@app.get("/api/history/{ticker}")
def get_history(ticker: str, limit: int = 60):
    """
    Mock endpoint for historical candle data
    Returns [Open, High, Low, Close, Volume]
    """
    base_price = 100.0 if ticker != "WIN" else 130000.0
    candles = []
    dates = []
    
    current_price = base_price
    for i in range(limit):
        # generate fake candle
        o = current_price
        c = current_price * (1 + (random.random() * 0.02 - 0.01))
        h = max(o, c) * (1 + random.random() * 0.005)
        l = min(o, c) * (1 - random.random() * 0.005)
        v = random.randint(1000, 50000)
        
        candles.append([round(o, 2), round(h, 2), round(l, 2), round(c, 2), v])
        dates.append(f"Day {i}")
        current_price = c

    return {"ticker": ticker, "candles": candles, "dates": dates}

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
