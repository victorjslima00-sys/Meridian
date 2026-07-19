"""API authentication configuration with no built-in credentials."""
import hmac
import os
from typing import Optional

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def get_api_key() -> Optional[str]:
    value = os.environ.get("API_KEY", "").strip()
    return value or None


def validate_security_config() -> None:
    key = get_api_key()
    if not key:
        raise RuntimeError(
            "API_KEY não configurada. Defina um segredo forte no ambiente antes de iniciar."
        )
    if len(key) < 16:
        raise RuntimeError("API_KEY deve ter pelo menos 16 caracteres")


def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    expected = get_api_key()
    if not expected or not hmac.compare_digest(api_key, expected):
        raise HTTPException(status_code=403, detail="Could not validate credentials")
    return api_key
