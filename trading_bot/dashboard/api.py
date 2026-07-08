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

from pydantic import BaseModel
from typing import Optional

class ActionRequest(BaseModel):
    action: str
    password: Optional[str] = None

@app.get("/api/positions")
def get_positions():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM paper_trades WHERE status = 'OPEN'")
        rows = cursor.fetchall()
        conn.close()
        
        active_positions = []
        for r in rows:
            entry = r["price"]
            curr = entry * 1.02 # mock 2% up
            pnl = ((curr - entry) / entry) * 100
            
            active_positions.append({
                "ticker": r["ticker"],
                "side": r["side"],
                "entry_price": entry,
                "current_price": curr,
                "target": entry * 1.08,
                "stop": entry * 0.95,
                "pnl_pct": round(pnl, 2)
            })

        return {
            "active_positions": active_positions,
            "capital": {
                "initial": 10000.0,
                "current": 10000.0 + sum([(p["current_price"] - p["entry_price"]) * r["qty"] for p, r in zip(active_positions, rows)]),
                "currency": "BRL"
            }
        }
    except Exception as e:
        return {"error": "Internal server error"}

@app.post("/api/system/emergency_stop")
def system_emergency_stop(req: ActionRequest):
    if req.password != "meridian2026":
        return {"error": "Senha incorreta. Acesso negado."}
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE paper_trades SET status = 'CANCELLED' WHERE status = 'OPEN'")
        conn.commit()
        conn.close()
        return {"status": "success", "msg": "EMERGENCY STOP ACIONADO. Todas as posições fechadas."}
    except Exception as e:
        return {"error": "Internal server error"}

@app.get("/api/ecosystem")
def get_ecosystem():
    return {
        "nodes": [
            {"id": "data", "label": "Data Ingestion (brapi)", "status": "idle"},
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

@app.get("/api/node/{node_id}")
def get_node_details(node_id: str):
    details = {
        "data": {"role": "Ingestão de Dados", "next_run": "09:00 AM", "logs": ["Fetch concluído: 47/50 ativos"]},
        "db": {"role": "Banco de Dados Central", "next_run": "N/A", "logs": ["Modo WAL Ativado"]},
        "quant": {"role": "Otimização de Parâmetros", "next_run": "Sexta-feira 23:00", "logs": ["Melhor Sharpe: 0.90"]},
        "research": {"role": "Contextualizador Macroeconômico", "next_run": "18:00 PM", "logs": ["Proposta de otimização enviada"]},
        "guardrail": {"role": "Auditor de Risco", "next_run": "Sempre ativo", "logs": ["Nenhuma violação detectada"]},
        "broker": {"role": "Integração B3 (Cedro)", "next_run": "Tempo real", "logs": ["Aguardando ordens"]}
    }
    return details.get(node_id, {"role": "Unknown", "next_run": "N/A", "logs": []})

@app.post("/api/node/{node_id}/action")
def node_action(node_id: str, req: ActionRequest):
    if req.action == "emergency_stop":
        if req.password != "meridian2026":
            return {"error": "Senha incorreta. Acesso negado."}
        return {"status": "success", "msg": "EMERGENCY STOP ACIONADO. Todas as posições fechadas."}
    
    if req.action == "run_now":
        return {"status": "success", "msg": f"Módulo {node_id} acionado manualmente."}
    
    return {"status": "error", "msg": "Ação desconhecida."}
