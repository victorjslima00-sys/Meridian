from datetime import date, datetime
from zoneinfo import ZoneInfo

def today_b3() -> date:
    """Retorna a data atual baseada no fuso de Brasília (onde a B3 opera)."""
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()
