from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import datetime
from pathlib import Path

app = FastAPI(title="Meridian Command Center API", version="1.0.0")

# Permitir acesso do frontend React (localhost:5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "trading_bot.db"

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/api/status")
def get_status():
    try:
        conn = get_db()
        conn.close()
        db_status = "online"
    except Exception:
        db_status = "offline"

    return {
        "status": "operational",
        "timestamp": datetime.datetime.now().isoformat(),
        "modules": {
            "database": db_status,
            "aws_ec2": "online",
            "guard_rail": "active",
            "broker_cedro": "paper_trading"
        }
    }

@app.get("/api/positions")
def get_positions():
    try:
        return {
            "active_positions": [
                {"ticker": "PETR4", "side": "BUY", "entry_price": 38.50, "current_price": 39.20, "target": 41.58, "stop": 36.57, "pnl_pct": 1.81},
                {"ticker": "ITUB4", "side": "BUY", "entry_price": 34.10, "current_price": 33.90, "target": 36.82, "stop": 32.39, "pnl_pct": -0.58},
                {"ticker": "WEGE3", "side": "BUY", "entry_price": 50.00, "current_price": 51.50, "target": 54.00, "stop": 47.50, "pnl_pct": 3.00}
            ],
            "capital": {
                "initial": 10000.0,
                "current": 10123.50,
                "currency": "BRL"
            }
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/ecosystem")
def get_ecosystem():
    return {
        "nodes": [
            {"id": "data", "label": "Data Ingestion (brapi/yfinance)", "status": "idle"},
            {"id": "db", "label": "SQLite (WAL Mode)", "status": "active"},
            {"id": "quant", "label": "Quant Optimizer", "status": "idle"},
            {"id": "research", "label": "Pesquisador IA", "status": "active"},
            {"id": "guardrail", "label": "Agente Guard-Rail", "status": "active"},
            {"id": "broker", "label": "Cedro Broker", "status": "active"}
        ],
        "edges": [
            {"source": "data", "target": "db", "animated": True},
            {"source": "quant", "target": "db", "animated": False},
            {"source": "db", "target": "research", "animated": True},
            {"source": "research", "target": "guardrail", "animated": True},
            {"source": "guardrail", "target": "broker", "animated": True}
        ]
    }
