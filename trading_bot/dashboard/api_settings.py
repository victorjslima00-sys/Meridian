from fastapi import APIRouter
from pydantic import BaseModel
import os

from trading_bot.broker.cedro_client import CedroClient

router = APIRouter(prefix='/api/system', tags=['system'])

# Armazena o modo em memória por simplicidade para a UI (em prod seria num yaml ou banco)
app_state = {
    "mode": "paper" # paper, cedro_sandbox, real
}

class ModeRequest(BaseModel):
    mode: str

@router.get('/settings')
def get_settings():
    """Retorna as configurações e status das chaves (sem expor as chaves)"""
    # Recarrega as vars do .env se houver
    from dotenv import load_dotenv
    load_dotenv()
    
    cedro_key = os.getenv("CEDRO_API_KEY")
    
    return {
        "mode": app_state["mode"],
        "has_cedro_key": bool(cedro_key and len(cedro_key) > 5 and cedro_key != "sua_api_key_aqui"),
        "env": os.getenv("CEDRO_ENV", "homologacao")
    }

@router.post('/settings/mode')
def set_mode(req: ModeRequest):
    """Altera o modo de operação"""
    if req.mode not in ['paper', 'cedro_sandbox', 'real']:
        return {"error": "Modo inválido"}
        
    app_state["mode"] = req.mode
    return {"status": "success", "mode": app_state["mode"]}

@router.post('/settings/validate_broker')
def validate_broker():
    """Faz um ping na Cedro para validar a chave"""
    from dotenv import load_dotenv
    load_dotenv()
    
    try:
        client = CedroClient()
        success, msg = client.validate_connection()
        return {
            "valid": success,
            "message": msg
        }
    except Exception as e:
        return {
            "valid": False,
            "message": str(e)
        }
