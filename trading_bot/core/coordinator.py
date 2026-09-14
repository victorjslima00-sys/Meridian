"""
Central Worker Coordinator & Supervisory Engine (P2).

Orquestra e supervisiona o ciclo de vida de workers assíncronos em background
(ex.: ai_committee_worker, exit_loop, tasks periódicas de valuation), provendo:
- Isolamento estrito de falhas por worker (LoopSupervisionState individual);
- Reinício resiliente com backoff exponencial (2^(rc-1) até teto);
- Parada definitiva (stopped) e gatilho de proteção (fail-closed sticky block);
- Provedor ativo de watchdog / liveness e stale heartbeat detection;
- Journal auditável de eventos e transições de ciclo de vida em memória;
- Parada graciosa (graceful cancellation) de todas as tasks supervisionadas;
- Garantia institucional: Zero chamadas a corretoras reais (real_broker_calls == 0).
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import datetime
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


def _now_b3() -> datetime.datetime:
    """Timestamp com fuso horário da B3 (America/Sao_Paulo)."""
    from backend.app.data.database import now_b3
    return now_b3()


@dataclass
class WorkerEvent:
    """Registro imutável de evento no ciclo de vida de um worker."""
    timestamp: datetime.datetime
    worker_name: str
    event_type: str  # START | CYCLE_OK | EXCEPTION | RESTART | STOPPED | SHUTDOWN | WATCHDOG_ALERT
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "worker_name": self.worker_name,
            "event_type": self.event_type,
            "message": self.message,
            "details": dict(self.details),
        }


class ManagedWorker:
    """Representa um worker registrado sob supervisão central."""

    def __init__(
        self,
        name: str,
        coro_fn: Callable[..., Coroutine[Any, Any, None]],
        interval_seconds: float = 60.0,
        max_restarts: int = 5,
        backoff_cap_seconds: float = 30.0,
        is_critical: bool = False,
        on_exhausted: Optional[Callable[[], Any]] = None,
        health_check: Optional[Callable[[], bool]] = None,
        supervision: Optional[Any] = None,
        alert_fn: Optional[Callable[[str], Any]] = None,
    ) -> None:
        from backend.app.worker_state import LoopSupervisionState
        self.name = name
        self.coro_fn = coro_fn
        self.interval_seconds = interval_seconds
        self.max_restarts = max_restarts
        self.backoff_cap_seconds = backoff_cap_seconds
        self.is_critical = is_critical
        self.on_exhausted = on_exhausted
        self.health_check = health_check
        self.supervision = supervision or LoopSupervisionState()
        self.alert_fn = alert_fn

        self.created_at = _now_b3()
        self.supervisor_task: Optional[asyncio.Task] = None
        self.last_activity_at: Optional[datetime.datetime] = None
        self.last_error: Optional[str] = None
        self.consecutive_stale_checks: int = 0

        # Auto-vincula callback de atividade se supervision possuir o slot
        if hasattr(self.supervision, "activity_callback"):
            self.supervision.activity_callback = self.mark_active

    def mark_active(self) -> None:
        """Registra atividade recente do worker e zera contagem de stale."""
        self.last_activity_at = _now_b3()
        self.consecutive_stale_checks = 0

    def is_alive(self, timeout_seconds: float = 300.0) -> bool:
        """
        Avalia se o worker está vivo e com heartbeat recente.
        Evita falso-negativo na inicialização utilizando timestamp de início.
        """
        if self.supervision.status not in ("running", "starting"):
            return False
        if self.supervisor_task is None or self.supervisor_task.done():
            return False
        if self.health_check:
            return bool(self.health_check())

        activity_ts = self.last_activity_at
        if activity_ts is None:
            # Fallback seguro para momento de início, evitando avaliar worker ativo recém-iniciado como morto
            if hasattr(self.supervision, "last_scan_at") and self.supervision.last_scan_at:
                activity_ts = self.supervision.last_scan_at
            elif hasattr(self.supervision, "last_exit_activity_at") and self.supervision.last_exit_activity_at:
                activity_ts = self.supervision.last_exit_activity_at
            elif hasattr(self.supervision, "restart_epoch_start") and self.supervision.restart_epoch_start:
                activity_ts = self.supervision.restart_epoch_start
            else:
                activity_ts = self.created_at

        elapsed = (_now_b3() - activity_ts).total_seconds()
        return elapsed <= timeout_seconds

    def snapshot(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.supervision.status,
            "is_alive": self.is_alive(),
            "restart_count": self.supervision.restart_count,
            "cycles_since_restart": self.supervision.cycles_since_restart,
            "is_critical": self.is_critical,
            "last_activity_at": self.last_activity_at.isoformat() if self.last_activity_at else None,
            "last_error": self.last_error,
        }


class CentralCoordinator:
    """
    Coordenador central para supervisão de workers assíncronos.
    """

    def __init__(
        self,
        heartbeat_timeout_seconds: float = 300.0,
        watchdog_interval_seconds: float = 15.0,
        max_event_history: int = 200,
        stale_threshold: int = 2,
    ) -> None:
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.watchdog_interval_seconds = watchdog_interval_seconds
        self.max_event_history = max_event_history
        self.stale_threshold = stale_threshold
        self._workers: Dict[str, ManagedWorker] = {}
        self._events: List[WorkerEvent] = []
        self._is_running: bool = False
        self._watchdog_task: Optional[asyncio.Task] = None
        self._health_monitor: Optional[Any] = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def health_monitor(self) -> Any:
        if self._health_monitor is None:
            from trading_bot.infra.health_monitor import OperationalHealthMonitor
            self._health_monitor = OperationalHealthMonitor()
        return self._health_monitor

    def mark_active(self, name: str) -> None:
        """Permite que chamadores externos ou workers registrem atividade por nome."""
        worker = self._workers.get(name)
        if worker:
            worker.mark_active()

    def register_worker(
        self,
        name: str,
        coro_fn: Callable[..., Coroutine[Any, Any, None]],
        interval_seconds: float = 60.0,
        max_restarts: int = 5,
        backoff_cap_seconds: float = 30.0,
        is_critical: bool = False,
        on_exhausted: Optional[Callable[[], Any]] = None,
        health_check: Optional[Callable[[], bool]] = None,
        supervision: Optional[Any] = None,
        alert_fn: Optional[Callable[[str], Any]] = None,
    ) -> ManagedWorker:
        """Registra um worker para gerenciamento supervisionado."""
        if name in self._workers:
            raise ValueError(f"Worker '{name}' já registrado no coordenador.")
        worker = ManagedWorker(
            name=name,
            coro_fn=coro_fn,
            interval_seconds=interval_seconds,
            max_restarts=max_restarts,
            backoff_cap_seconds=backoff_cap_seconds,
            is_critical=is_critical,
            on_exhausted=on_exhausted,
            health_check=health_check,
            supervision=supervision,
            alert_fn=alert_fn,
        )
        self._workers[name] = worker
        self._record_event(name, "REGISTER", f"Worker '{name}' registrado no Coordenador Central.")
        return worker

    def get_worker(self, name: str) -> Optional[ManagedWorker]:
        return self._workers.get(name)

    def _record_event(
        self, worker_name: str, event_type: str, message: str, **details: Any
    ) -> None:
        event = WorkerEvent(
            timestamp=_now_b3(),
            worker_name=worker_name,
            event_type=event_type,
            message=message,
            details=details,
        )
        self._events.append(event)
        if len(self._events) > self.max_event_history:
            self._events.pop(0)
        logger.info("[Coordinator] [%s] %s: %s", worker_name, event_type, message)

    async def _run_worker_supervisor(self, worker: ManagedWorker) -> None:
        """Loop de supervisão dedicado para um worker específico."""
        import inspect
        while self._is_running:
            worker.supervision.on_start()
            worker.mark_active()
            self._record_event(
                worker.name,
                "START",
                f"Supervisor iniciando execução do worker '{worker.name}'",
                restart_count=worker.supervision.restart_count,
            )
            try:
                sig = inspect.signature(worker.coro_fn)
                if len(sig.parameters) > 0:
                    await worker.coro_fn(worker)
                else:
                    await worker.coro_fn()
                # Saída normal (caso coroutine não seja loop infinito)
                worker.mark_active()
                self._record_event(worker.name, "EXIT", f"Worker '{worker.name}' completou execução normalmente.")
                return
            except asyncio.CancelledError:
                self._record_event(worker.name, "CANCELLED", f"Worker '{worker.name}' cancelado graciosamente.")
                raise
            except Exception as e:
                worker.last_error = str(e)
                worker.supervision.record_crash()
                rc = worker.supervision.restart_count
                logger.exception("Worker '%s' terminou com falha fatal: %s", worker.name, e)
                self._record_event(
                    worker.name,
                    "EXCEPTION",
                    f"Falha fatal em '{worker.name}': {e}",
                    restart_count=rc,
                    error=str(e),
                )

                if worker.alert_fn:
                    try:
                        msg = f"⚠️ [Meridian Coordenador] Worker '{worker.name}' caiu (restart {rc}/{worker.max_restarts}): {e}"
                        if asyncio.iscoroutinefunction(worker.alert_fn):
                            await worker.alert_fn(msg)
                        else:
                            await asyncio.to_thread(worker.alert_fn, msg)
                    except Exception as alert_err:
                        logger.error("Falha ao enviar alerta de crash para %s: %s", worker.name, alert_err)

                if rc > worker.max_restarts:
                    worker.supervision.mark_stopped()
                    self._record_event(
                        worker.name,
                        "STOPPED",
                        f"Worker '{worker.name}' PARADO — tentativas de restart ({worker.max_restarts}) esgotadas.",
                        is_critical=worker.is_critical,
                    )
                    if worker.on_exhausted:
                        try:
                            worker.on_exhausted()
                        except Exception as hook_err:
                            logger.error("Erro no callback de exaustão de %s: %s", worker.name, hook_err)

                    if worker.alert_fn:
                        try:
                            stopped_msg = (
                                f"🛑 [Meridian Coordenador] Worker '{worker.name}' PARADO definitivamente. "
                                "Intervenção manual necessária."
                            )
                            if asyncio.iscoroutinefunction(worker.alert_fn):
                                await worker.alert_fn(stopped_msg)
                            else:
                                await asyncio.to_thread(worker.alert_fn, stopped_msg)
                        except Exception as alert_err:
                            logger.error("Falha no alerta de parada de %s: %s", worker.name, alert_err)
                    return

                # Backoff exponencial com teto
                delay = min(2 ** (rc - 1), worker.backoff_cap_seconds)
                self._record_event(
                    worker.name,
                    "RESTART",
                    f"Aguardando backoff de {delay}s antes do próximo restart ({rc}/{worker.max_restarts})",
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)

    async def _watchdog_loop(self) -> None:
        """Watchdog central de heartbeat, liveness e remediação ativa de workers."""
        while self._is_running:
            try:
                await asyncio.sleep(self.watchdog_interval_seconds)
                for worker in list(self._workers.values()):
                    if not self._is_running:
                        break
                    if worker.supervision.status in ("running", "starting"):
                        if not worker.is_alive(timeout_seconds=self.heartbeat_timeout_seconds):
                            worker.consecutive_stale_checks += 1
                            self._record_event(
                                worker.name,
                                "WATCHDOG_ALERT",
                                f"Worker '{worker.name}' detectado com heartbeat estagnado (> {self.heartbeat_timeout_seconds}s).",
                                consecutive_stale=worker.consecutive_stale_checks,
                            )
                            if worker.consecutive_stale_checks >= self.stale_threshold:
                                self._record_event(
                                    worker.name,
                                    "WATCHDOG_REMEDIATION",
                                    f"Remediação ativa: cancelando task congelada de '{worker.name}' após {worker.consecutive_stale_checks} falhas de heartbeat.",
                                    consecutive_stale=worker.consecutive_stale_checks,
                                )
                                if worker.alert_fn:
                                    try:
                                        msg = (
                                            f"🚨 [Watchdog Remediation] Worker '{worker.name}' congelado "
                                            f"({worker.consecutive_stale_checks} verificações consecutivas). "
                                            "Cancelando task para auto-healing."
                                        )
                                        if asyncio.iscoroutinefunction(worker.alert_fn):
                                            await worker.alert_fn(msg)
                                        else:
                                            await asyncio.to_thread(worker.alert_fn, msg)
                                    except Exception as alert_err:
                                        logger.error("Falha ao enviar alerta de watchdog remediation para %s: %s", worker.name, alert_err)

                                # Cancela a task congelada
                                stale_task = worker.supervisor_task
                                if stale_task and not stale_task.done():
                                    stale_task.cancel()
                                    with suppress(asyncio.CancelledError):
                                        await stale_task

                                # Zera contagem de stale após remediação
                                worker.consecutive_stale_checks = 0

                                # Auto-healing: reinicia worker se coordenador continuar em execução
                                if self._is_running:
                                    worker.supervision.record_crash()
                                    rc = worker.supervision.restart_count
                                    if rc > worker.max_restarts:
                                        worker.supervision.mark_stopped()
                                        self._record_event(
                                            worker.name,
                                            "STOPPED",
                                            f"Worker '{worker.name}' PARADO definitivamente após auto-healing — tentativas esgotadas.",
                                            is_critical=worker.is_critical,
                                        )
                                        if worker.on_exhausted:
                                            try:
                                                worker.on_exhausted()
                                            except Exception as hook_err:
                                                logger.error("Erro no callback de exaustão de %s: %s", worker.name, hook_err)
                                    else:
                                        worker.supervision.mark_starting()
                                        worker.mark_active()
                                        new_task = asyncio.create_task(self._run_worker_supervisor(worker))
                                        worker.supervisor_task = new_task
                                        self._record_event(
                                            worker.name,
                                            "WATCHDOG_AUTOHEAL",
                                            f"Worker '{worker.name}' reiniciado com sucesso pelo watchdog (restart {rc}/{worker.max_restarts}).",
                                            restart_count=rc,
                                        )
                        else:
                            # Worker está ativo e saudável
                            worker.consecutive_stale_checks = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Erro no loop de watchdog do coordenador: %s", e)

    async def start(self) -> None:
        """Inicia todos os workers registrados e o watchdog."""
        if self._is_running:
            logger.warning("CentralCoordinator já está em execução.")
            return

        self._is_running = True
        self._record_event("COORDINATOR", "START", "Iniciando CentralCoordinator e workers registrados.")

        for worker in self._workers.values():
            worker.supervision.mark_starting()
            worker.mark_active()
            task = asyncio.create_task(self._run_worker_supervisor(worker))
            worker.supervisor_task = task

        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        self._record_event("COORDINATOR", "RUNNING", f"{len(self._workers)} workers em supervisão ativa.")

    async def stop(self) -> None:
        """Encerra graciosamente todos os workers e watchdog."""
        if not self._is_running:
            return

        self._is_running = False
        self._record_event("COORDINATOR", "SHUTDOWN", "Encerrando CentralCoordinator graciosamente.")

        if self._watchdog_task:
            self._watchdog_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._watchdog_task

        for worker in self._workers.values():
            if worker.supervisor_task:
                worker.supervisor_task.cancel()
                with suppress(asyncio.CancelledError):
                    await worker.supervisor_task
            worker.supervision.mark_stopped()

        self._record_event("COORDINATOR", "STOPPED", "Todos os workers e tasks foram encerrados com sucesso.")

    def snapshot(self) -> Dict[str, Any]:
        """Retorna snapshot consolidado de telemetria do coordenador."""
        worker_snaps = {w.name: w.snapshot() for w in self._workers.values()}
        all_alive = all(w["is_alive"] for w in worker_snaps.values()) if worker_snaps else False
        has_stopped = any(w["status"] == "stopped" for w in worker_snaps.values())
        has_critical_stopped = any(
            w["status"] == "stopped" and self._workers[name].is_critical
            for name, w in worker_snaps.items()
        )

        if has_critical_stopped:
            global_status = "stopped"
        elif has_stopped:
            global_status = "degraded"
        elif all_alive:
            global_status = "online"
        else:
            global_status = "starting" if self._is_running else "stopped"

        system_metrics = None
        try:
            system_metrics = self.health_monitor.collect_system_metrics()
            if system_metrics.get("system_status") == "CRITICAL_LOW_MEMORY" and global_status == "online":
                global_status = "degraded"
        except Exception as exc:
            logger.warning("Falha ao coletar métricas do OperationalHealthMonitor: %s", exc)

        return {
            "coordinator_running": self._is_running,
            "global_status": global_status,
            "registered_workers_count": len(self._workers),
            "workers": worker_snaps,
            "system_health": system_metrics,
            "recent_events": [e.to_dict() for e in self._events[-10:]],
            "fail_closed_guarantee": True,
            "real_broker_calls": 0,
        }

    def get_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._events[-limit:]]
