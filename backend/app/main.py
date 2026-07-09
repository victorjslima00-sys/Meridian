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
    tickers_to_watch = ["PETR4.SA", "VALE3.SA", "ITUB4.SA"]
    
    while True:
        await asyncio.sleep(5) # start 5s after boot
        print("Starting AI committee scan loop...", flush=True)
        for ticker in tickers_to_watch:
            print(f"Scanning {ticker}...", flush=True)
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
                    
                    # 3. Executor
                    executor = ExecutorAgent()
                    res = executor.execute_order(ticker, decision, analysis['last_price'])
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
    trades = get_trades()
    return {
        "capital": {
            "initial": pf.get('initial_capital', 10000.0),
            "current": pf.get('current_capital', 10500.0),
            "invested": pf.get('invested_capital', 1200.0)
        },
        "active_positions": []
    }

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
