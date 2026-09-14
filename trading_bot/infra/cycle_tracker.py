"""
Cycle Latency & Execution Duration Tracking Helper — Vulcan Observability.

Provides timing, execution metrics, and latency anomaly detection for repetitive
background workers and scan loops (e.g. exit_loop, ai_committee_worker).
Prevents silent latency inflation, records delayed cycle statistics, and exports
structured telemetry for system health inspection.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
import datetime
import logging
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CycleMetric:
    """Registro imutável de uma iteração de execução."""
    name: str
    duration_seconds: float
    started_at: float
    completed_at: float
    is_delayed: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "duration_seconds": round(self.duration_seconds, 4),
            "is_delayed": self.is_delayed,
            "details": dict(self.details),
        }


class CycleLatencyTracker:
    """
    Rastreador de latência de ciclo para loops operacionais.
    
    Calcula duração de cada iteração, identifica ciclos atrasados (que excedem
    o limiar esperado), rastreia médias e percentis aproximados, e notifica
    via callback opcional em caso de degradação.
    """

    def __init__(
        self,
        name: str = "default",
        warn_threshold_seconds: float = 10.0,
        max_history: int = 100,
        on_delayed_cycle: Optional[Callable[[CycleMetric], Any]] = None,
    ) -> None:
        self.name = name
        self.warn_threshold_seconds = warn_threshold_seconds
        self.max_history = max_history
        self.on_delayed_cycle = on_delayed_cycle

        self.total_cycles: int = 0
        self.delayed_cycles_count: int = 0
        self.last_cycle_duration_seconds: Optional[float] = None
        self.min_duration_seconds: Optional[float] = None
        self.max_duration_seconds: Optional[float] = None
        self._total_duration_seconds: float = 0.0
        self._history: List[CycleMetric] = []

    @property
    def avg_duration_seconds(self) -> Optional[float]:
        if self.total_cycles == 0:
            return None
        return round(self._total_duration_seconds / self.total_cycles, 4)

    def record_cycle(
        self,
        duration_seconds: float,
        started_at: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> CycleMetric:
        """Registra a duração de um ciclo concluído."""
        now = time.monotonic()
        start = started_at if started_at is not None else (now - duration_seconds)
        is_delayed = duration_seconds >= self.warn_threshold_seconds

        self.total_cycles += 1
        self.last_cycle_duration_seconds = round(duration_seconds, 4)
        self._total_duration_seconds += duration_seconds

        if self.min_duration_seconds is None or duration_seconds < self.min_duration_seconds:
            self.min_duration_seconds = round(duration_seconds, 4)
        if self.max_duration_seconds is None or duration_seconds > self.max_duration_seconds:
            self.max_duration_seconds = round(duration_seconds, 4)

        if is_delayed:
            self.delayed_cycles_count += 1
            logger.warning(
                "[CycleLatencyTracker] Ciclo '%s' com latência excessiva: %.3fs (limiar: %.1fs)",
                self.name,
                duration_seconds,
                self.warn_threshold_seconds,
            )

        metric = CycleMetric(
            name=self.name,
            duration_seconds=duration_seconds,
            started_at=start,
            completed_at=now,
            is_delayed=is_delayed,
            details=details or {},
        )

        self._history.append(metric)
        if len(self._history) > self.max_history:
            self._history.pop(0)

        if is_delayed and self.on_delayed_cycle:
            try:
                self.on_delayed_cycle(metric)
            except Exception as e:
                logger.error("Erro no callback on_delayed_cycle de %s: %s", self.name, e)

        return metric

    @contextmanager
    def measure(self, details: Optional[Dict[str, Any]] = None):
        """Context manager síncrono para medição do tempo de um ciclo."""
        start = time.monotonic()
        try:
            yield
        finally:
            duration = time.monotonic() - start
            self.record_cycle(duration, started_at=start, details=details)

    @asynccontextmanager
    async def measure_async(self, details: Optional[Dict[str, Any]] = None):
        """Context manager assíncrono para medição do tempo de um ciclo."""
        start = time.monotonic()
        try:
            yield
        finally:
            duration = time.monotonic() - start
            self.record_cycle(duration, started_at=start, details=details)

    def snapshot(self) -> Dict[str, Any]:
        """Retorna snapshot estruturado para exposição em status e telemetria."""
        return {
            "name": self.name,
            "total_cycles": self.total_cycles,
            "delayed_cycles_count": self.delayed_cycles_count,
            "last_cycle_duration_seconds": self.last_cycle_duration_seconds,
            "avg_duration_seconds": self.avg_duration_seconds,
            "min_duration_seconds": self.min_duration_seconds,
            "max_duration_seconds": self.max_duration_seconds,
            "warn_threshold_seconds": self.warn_threshold_seconds,
            "is_currently_delayed": (
                self.last_cycle_duration_seconds is not None
                and self.last_cycle_duration_seconds >= self.warn_threshold_seconds
            ),
        }
