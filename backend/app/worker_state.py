"""
Estado observável do worker autônomo (ai_committee_worker) — heartbeat e
supervisão de restart.

Um bot que gerencia stop-loss e morre em silêncio é perigoso: a API não pode
responder "online" com o worker morto. Este módulo mantém um estado singleton
que o `/api/status` expõe (last_scan_at / worker_alive) e que o supervisor usa
para decidir restart com backoff e desistência.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, Optional

from .data.database import now_b3

logger = logging.getLogger(__name__)

# --- Parâmetros de supervisão (tests podem monkeypatchar) -------------------
HEARTBEAT_TIMEOUT_SECONDS = 300   # sem heartbeat por > 5 min → worker_alive False
SCAN_INTERVAL_SECONDS = 60        # intervalo entre ciclos do worker (laço lento, entradas)
EXIT_INTERVAL_SECONDS = 5         # intervalo do laço rápido de saídas (P3-A Etapa 2)
MAX_RESTARTS = 5                  # restarts consecutivos antes de desistir
BACKOFF_CAP_SECONDS = 30          # teto do backoff exponencial
STABLE_RESET_CYCLES = 5           # ciclos estáveis para zerar restart_count
STABLE_RESET_SECONDS = 600        # OU tempo estável (10 min) para zerar


class WorkerState:
    """Estado mutável do worker. Instância única em `state` (abaixo)."""

    def __init__(self) -> None:
        self.status: str = "starting"   # starting | running | stopped
        self.last_scan_at: Optional[datetime.datetime] = None
        self.restart_count: int = 0
        self.cycles_since_restart: int = 0
        self.restart_epoch_start: datetime.datetime = now_b3()

    # -- Transições ---------------------------------------------------------
    def mark_starting(self) -> None:
        self.status = "starting"

    def on_worker_start(self) -> None:
        """Chamado pelo supervisor antes de cada (re)entrada no worker."""
        self.status = "running"
        self.cycles_since_restart = 0
        self.restart_epoch_start = now_b3()

    def mark_scan(self) -> None:
        """Registra uma iteração completa (heartbeat) e aplica reset por estabilidade."""
        self.last_scan_at = now_b3()
        self.status = "running"
        self.cycles_since_restart += 1
        self._maybe_reset_restart_count()

    def record_crash(self) -> None:
        self.restart_count += 1

    def mark_stopped(self) -> None:
        self.status = "stopped"

    # -- Reset por estabilidade --------------------------------------------
    def _maybe_reset_restart_count(self) -> None:
        """
        Zera restart_count SÓ se o worker estiver estável desde o último restart:
        >= STABLE_RESET_CYCLES ciclos OU >= STABLE_RESET_SECONDS de duração.

        Resetar após 1 único ciclo permitiria crash-loop infinito (1 ciclo →
        morre → reseta → repete, sem nunca desistir). Por isso o reset exige
        uma janela de estabilidade.
        """
        if self.restart_count == 0:
            return
        elapsed = (now_b3() - self.restart_epoch_start).total_seconds()
        if (
            self.cycles_since_restart >= STABLE_RESET_CYCLES
            or elapsed >= STABLE_RESET_SECONDS
        ):
            logger.info(
                "Worker estável (%d ciclos, %.0fs) — zerando restart_count.",
                self.cycles_since_restart,
                elapsed,
            )
            self.restart_count = 0

    # -- Leitura ------------------------------------------------------------
    def is_alive(self) -> bool:
        if self.status != "running" or self.last_scan_at is None:
            return False
        elapsed = (now_b3() - self.last_scan_at).total_seconds()
        return elapsed < HEARTBEAT_TIMEOUT_SECONDS

    def snapshot(self) -> Dict[str, Any]:
        alive = self.is_alive()
        return {
            "status": "online" if alive else ("stopped" if self.status == "stopped" else "degraded"),
            "worker_alive": alive,
            "worker_status": self.status,
            "last_scan_at": self.last_scan_at.isoformat() if self.last_scan_at else None,
            "restart_count": self.restart_count,
        }

    def reset(self) -> None:
        """Reinicia o estado (usado por testes)."""
        self.__init__()


# Instância singleton usada por main.py e /api/status
state = WorkerState()
