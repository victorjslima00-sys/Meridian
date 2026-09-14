"""
Motor Central de Alertas Operacionais e Despacho de Eventos — Vulcan DevOps
Head of Infrastructure: Vulcan
Meridian Technologies
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import asdict, dataclass
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AlertMessage:
    level: str       # INFO, WARNING, CRITICAL, EMERGENCY
    sector: str      # DATA, QUANT, RISK, INFRA, ANALYTICS
    title: str
    details: str
    timestamp_utc: Optional[str] = None

    def __post_init__(self):
        if self.timestamp_utc is None:
            self.timestamp_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AlertsEngine:
    """
    Roteador de alertas institucionais. Registra historico de incidentes,
    notifica logs internos e prepara payloads para canais externos (Telegram/Webhooks).
    """

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.history: List[dict[str, Any]] = []

    def dispatch(self, alert: AlertMessage) -> dict[str, Any]:
        """
        Registra e despacha o alerta.
        """
        record = alert.to_dict()
        self.history.append(record)

        if len(self.history) > self.max_history:
            self.history.pop(0)

        log_fn = logger.info
        if alert.level == "WARNING":
            log_fn = logger.warning
        elif alert.level in ("CRITICAL", "EMERGENCY"):
            log_fn = logger.critical

        log_fn("[%s][%s] %s: %s", alert.sector, alert.level, alert.title, alert.details)

        return {
            "dispatched": True,
            "level": alert.level,
            "sector": alert.sector,
            "timestamp_utc": alert.timestamp_utc,
        }
