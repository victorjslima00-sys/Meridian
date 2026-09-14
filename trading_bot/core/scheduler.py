import asyncio
import logging
import schedule
import time
from typing import Any, Callable, Coroutine, Optional, List

logger = logging.getLogger(__name__)


class Scheduler:
    """Wrapper para o schedule, roda as tarefas no horario especificado.
    
    Suporta tanto agendamentos síncronos legados (schedule) quanto
    integração assíncrona com o CentralCoordinator.
    """
    def __init__(self, coordinator: Optional[Any] = None):
        self._running = False
        self._coordinator = coordinator
        self._async_jobs: List[dict] = []
        
    def bind_coordinator(self, coordinator: Any) -> None:
        """Associa um CentralCoordinator ao Scheduler."""
        self._coordinator = coordinator

    @property
    def coordinator(self) -> Optional[Any]:
        return self._coordinator

    def add_daily_job(self, time_str: str, job_func: Callable):
        schedule.every().day.at(time_str).do(job_func)
        logger.info("Job added for %s", time_str)
        
    def run_pending(self):
        schedule.run_pending()
        
    def start_blocking(self):
        self._running = True
        logger.info("Scheduler started (blocking mode).")
        while self._running:
            self.run_pending()
            time.sleep(60)
            
    def stop(self):
        self._running = False
        logger.info("Scheduler stopped.")

    def add_async_job(self, name: str, coro_fn: Callable[[], Coroutine], interval_seconds: float = 60.0):
        """Registra uma tarefa assíncrona recorrente."""
        if self._coordinator:
            self._coordinator.register_worker(name=name, coro_fn=coro_fn, interval_seconds=interval_seconds)
        else:
            self._async_jobs.append({"name": name, "coro_fn": coro_fn, "interval_seconds": interval_seconds})

    async def start_async(self):
        """Inicia o laço assíncrono do agendador e coordena workers caso vinculados."""
        self._running = True
        logger.info("Scheduler started (async mode).")
        if self._coordinator and not self._coordinator.is_running:
            await self._coordinator.start()

        while self._running:
            self.run_pending()
            await asyncio.sleep(1)
