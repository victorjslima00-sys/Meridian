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


class LoopSupervisionState:
    """Contabilidade de restart/backoff de UM laço supervisionado — P3-A
    Etapa 4. Cada laço (entrada, saída) tem sua PRÓPRIA instância: a
    instabilidade de um não pode derrubar a supervisão do outro, que pode
    estar são. É por isso que este objeto existe separado de WorkerState
    (que mantém os campos da entrada inline, por compatibilidade com o
    código anterior à Etapa 4) em vez de um contador global único.

    use_cycles_for_stability=False (usado pelo exit_loop, cadência ~5s):
    o reset por estabilidade usa SÓ STABLE_RESET_SECONDS, nunca contagem
    de ciclos. STABLE_RESET_CYCLES=5 foi calibrado para a cadência da
    entrada (60s/ciclo → 5 min); na saída (5s/ciclo) isso seria só 25s,
    tempo curto demais pra provar qualquer estabilidade de verdade.
    """

    def __init__(self, use_cycles_for_stability: bool = True) -> None:
        self.status: str = "starting"   # starting | running | stopped
        self.restart_count: int = 0
        self.cycles_since_restart: int = 0
        self.restart_epoch_start: datetime.datetime = now_b3()
        self.use_cycles_for_stability = use_cycles_for_stability

    def mark_starting(self) -> None:
        self.status = "starting"

    def on_start(self) -> None:
        """Chamado pelo supervisor antes de cada (re)entrada no laço."""
        self.status = "running"
        self.cycles_since_restart = 0
        self.restart_epoch_start = now_b3()

    def mark_cycle_complete(self) -> None:
        """Chamado a cada iteração bem-sucedida do laço supervisionado —
        reavalia a janela de estabilidade."""
        self.status = "running"
        self.cycles_since_restart += 1
        self._maybe_reset_restart_count()

    def record_crash(self) -> None:
        self.restart_count += 1

    def mark_stopped(self) -> None:
        self.status = "stopped"

    def _maybe_reset_restart_count(self) -> None:
        """Mesma lógica de WorkerState._maybe_reset_restart_count, agora
        reutilizável por laço. Ver docstring da classe sobre
        use_cycles_for_stability."""
        if self.restart_count == 0:
            return
        elapsed = (now_b3() - self.restart_epoch_start).total_seconds()
        stable = elapsed >= STABLE_RESET_SECONDS
        if self.use_cycles_for_stability:
            stable = stable or self.cycles_since_restart >= STABLE_RESET_CYCLES
        if stable:
            logger.info(
                "Laço estável (%d ciclos, %.0fs) — zerando restart_count.",
                self.cycles_since_restart,
                elapsed,
            )
            self.restart_count = 0


class WorkerState:
    """Estado mutável do worker. Instância única em `state` (abaixo)."""

    def __init__(self) -> None:
        self.status: str = "starting"   # starting | running | stopped
        self.last_scan_at: Optional[datetime.datetime] = None
        self.restart_count: int = 0
        self.cycles_since_restart: int = 0
        self.restart_epoch_start: datetime.datetime = now_b3()
        # Heartbeat granular do exit_loop (P3-A Etapa 3) — dois sinais
        # DELIBERADAMENTE separados: last_exit_activity_at prova que o laço
        # está rodando; last_effective_exit_scan_at prova que ele está de
        # fato PROTEGENDO (toda posição ativa avaliada com preço confiável,
        # ou nenhuma existia — zero posições é uma passada trivialmente
        # efetiva). Um laço vivo mas inefetivo (girando sem avaliar nada,
        # por rate limit ou feed fora do ar) não pode passar por saudável —
        # ver is_alive()/_compute_status().
        self.last_exit_activity_at: Optional[datetime.datetime] = None
        self.last_effective_exit_scan_at: Optional[datetime.datetime] = None
        # Supervisão do exit_loop (P3-A Etapa 4) — contabilidade PRÓPRIA,
        # nunca compartilhada com a da entrada (campos acima, inalterados
        # desde antes da Etapa 4).
        self.exit_supervision = LoopSupervisionState(use_cycles_for_stability=False)
        # Bloqueio STICKY de novas entradas: setado quando exit_supervision
        # esgota MAX_RESTARTS. Só reset() (reinício do processo em
        # produção) limpa — NUNCA a saída voltando a ficar saudável
        # sozinha. Esgotar restarts significa algo estruturalmente
        # quebrado; a decisão de voltar a operar é do operador, não
        # automática. Ver set_exit_gate_sticky_block().
        self.exit_gate_sticky_block: bool = False
        # Motivos da última avaliação do portão único de entradas
        # (honest-dashboard, Bloco 1) — persistidos aqui para que /api/status
        # possa expor POR QUE as entradas estão bloqueadas sem o frontend
        # precisar recalcular nada. Antes deste campo, _avaliar_portao_de_
        # entradas calculava os motivos e descartava no fim do próprio ciclo.
        self.last_gate_motivos: list = []

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

    def mark_exit_activity(self, effective: bool) -> None:
        """Chamado pelo exit_loop ao fim de CADA iteração bem-sucedida
        (sem exceção — mesma convenção de mark_scan/ai_committee_worker).
        `effective` vem do retorno de _run_exit_scan(): True se toda
        posição ativa foi avaliada com preço confiável (ou não havia
        nenhuma). last_exit_activity_at sempre avança;
        last_effective_exit_scan_at só avança quando effective=True."""
        now = now_b3()
        self.last_exit_activity_at = now
        if effective:
            self.last_effective_exit_scan_at = now

    def mark_gate_evaluated(self, motivos: list) -> None:
        """Chamado por _avaliar_portao_de_entradas ao fim de cada avaliação
        (honest-dashboard, Bloco 1) — guarda o resultado para /api/status
        expor. Sobrescreve sempre: motivos refletem a avaliação MAIS
        recente, de qualquer chamador (laço automático ou ordem manual) —
        ambos calculam a mesma verdade a partir do mesmo estado ao vivo."""
        self.last_gate_motivos = list(motivos)

    def set_exit_gate_sticky_block(self) -> None:
        """Chamado só quando exit_supervision esgota MAX_RESTARTS (P3-A
        Etapa 4). Deliberadamente NÃO há um método simétrico de "limpar" —
        o único jeito de reverter isto é reset() (reinício do processo em
        produção). Ver docstring do campo exit_gate_sticky_block."""
        self.exit_gate_sticky_block = True

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
    def _fresh(self, ts: Optional[datetime.datetime]) -> bool:
        if ts is None:
            return False
        return (now_b3() - ts).total_seconds() < HEARTBEAT_TIMEOUT_SECONDS

    def is_exit_loop_healthy(self) -> bool:
        """Saída viva E efetiva — os dois sinais da Etapa 3 frescos.
        Reutilizado tanto por _compute_status() (visão de sistema) quanto
        pelo portão de entradas (decisão de negócio, Etapa 4)."""
        return self._fresh(self.last_exit_activity_at) and self._fresh(
            self.last_effective_exit_scan_at
        )

    def _compute_status(self) -> str:
        """Fonte única dos 4 estados de /api/status (P3-A Etapa 4), nesta
        ordem de prioridade — a primeira condição que bater decide:

        1. stopped: exit_supervision esgotou os restarts (sticky, mais
           severo — capital exposto, ninguém tentando mais reiniciar).
        2. unprotected: saída não está viva+efetiva AGORA, independente do
           estado da entrada — cobre tanto "girando sem proteger" quanto
           "nem está rodando" (efetividade nunca é mais fresca que
           atividade, ver mark_exit_activity). Não pode ser "online" nem
           cair no mesmo "degraded" de entrada-morta: são urgências
           diferentes, uma é o modo seguro projetado, a outra é exposição
           real sem proteção.
        3. degraded: entrada morta/stale, mas saída viva e efetiva — o
           estado seguro de sempre (CLAUDE.md: gerenciar saídas é
           permitido mesmo com o resto bloqueado).
        4. online: tudo fresco.
        """
        if self.exit_supervision.status == "stopped":
            return "stopped"
        if not self.is_exit_loop_healthy():
            return "unprotected"
        if self.status != "running" or not self._fresh(self.last_scan_at):
            return "degraded"
        return "online"

    def is_alive(self) -> bool:
        """worker_alive é estrito: só True quando o sistema está
        plenamente 'online' (ver _compute_status)."""
        return self._compute_status() == "online"

    def snapshot(self) -> Dict[str, Any]:
        status = self._compute_status()
        return {
            "status": status,
            "worker_alive": status == "online",
            "worker_status": self.status,
            "last_scan_at": self.last_scan_at.isoformat() if self.last_scan_at else None,
            "last_exit_activity_at": (
                self.last_exit_activity_at.isoformat()
                if self.last_exit_activity_at else None
            ),
            "last_effective_exit_scan_at": (
                self.last_effective_exit_scan_at.isoformat()
                if self.last_effective_exit_scan_at else None
            ),
            "restart_count": self.restart_count,
            "exit_restart_count": self.exit_supervision.restart_count,
            "exit_gate_sticky_block": self.exit_gate_sticky_block,
            "motivos_bloqueio": list(self.last_gate_motivos),
        }

    def reset(self) -> None:
        """Reinicia o estado (usado por testes)."""
        self.__init__()


# Instância singleton usada por main.py e /api/status
state = WorkerState()
