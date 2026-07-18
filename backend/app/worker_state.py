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


# --- TTL do cache de preço no caminho de SAÍDA (P3-A Etapa 2e) --------------
# O laço de saída (exit_loop/_run_exit_scan) usa um TTL de cache mais curto
# que o default de entrada (feed.PRICE_CACHE_TTL_SECONDS) — saída tolera
# muito menos dado velho que entrada (CLAUDE.md: "gerenciar saídas é
# permitido" mesmo com o resto bloqueado; ver também BACKLOG.md sobre
# latência de stop-loss).
#
# FÓRMULA DO ATRASO MÁXIMO NA DETECÇÃO DE UM STOP (medida contra o pior
# caso: o preço cruza o stop logo depois de uma leitura fresca cachear o
# valor antigo):
#
#     atraso_pior_caso = (⌊TTL / EXIT_INTERVAL⌋ + 1) × EXIT_INTERVAL
#                      = TTL + EXIT_INTERVAL − (TTL mod EXIT_INTERVAL)
#
# Isso é NO MÁXIMO TTL + EXIT_INTERVAL, e SÓ atinge esse teto quando TTL é
# múltiplo exato de EXIT_INTERVAL (TTL mod EXIT_INTERVAL == 0) — por isso o
# TTL de saída é DERIVADO de EXIT_INTERVAL_SECONDS (2×), nunca um número
# solto: um valor solto que deixasse de ser múltiplo do intervalo faria a
# fórmula acima "vazar" (o atraso real fica MENOR que TTL+INTERVALO, mas de
# um jeito não-óbvio — o teto documentado deixaria de ser exato sem que
# ninguém percebesse ao mudar uma das duas constantes isoladamente).
#
# Ressalva: esta conta assume execução de scan instantânea. Na prática,
# _run_exit_scan busca N tickers em sequência antes do próximo
# asyncio.sleep(EXIT_INTERVAL_SECONDS), então o espaçamento real entre
# scans é EXIT_INTERVAL_SECONDS + tempo_de_busca — com mais posições
# ativas ou rede lenta, o atraso real do pior caso só cresce, nunca
# encolhe. A fórmula acima é um piso, não uma garantia absoluta.
def exit_price_cache_ttl_seconds() -> int:
    """TTL do cache de preço para fetch_recent_data(..., ttl=...) no
    exit_loop. Lida ao vivo (não congelada em import) — se
    EXIT_INTERVAL_SECONDS for monkeypatchado (teste) ou mudar (config
    futura), o valor derivado acompanha automaticamente, sem risco de
    desalinhar a fórmula documentada acima."""
    return 2 * EXIT_INTERVAL_SECONDS


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
