"""
Testes unitários para o CycleLatencyTracker (Vulcan Observability).
Cobre:
- Registro de ciclos e cálculo de duração;
- Métricas agregadas (mínimo, máximo, média, total);
- Detecção e contabilidade de ciclos com latência excessiva (delayed);
- Context managers síncronos e assíncronos;
- Disparo de callbacks em caso de ciclos atrasados;
- Estrutura de snapshot de integridade para /api/status.
"""
import asyncio
import time
from unittest.mock import MagicMock

import pytest

from trading_bot.infra.cycle_tracker import CycleLatencyTracker, CycleMetric


def test_cycle_latency_tracker_basic_record():
    tracker = CycleLatencyTracker(name="test_worker", warn_threshold_seconds=0.5)
    assert tracker.name == "test_worker"
    assert tracker.total_cycles == 0
    assert tracker.delayed_cycles_count == 0
    assert tracker.avg_duration_seconds is None

    metric = tracker.record_cycle(0.12)
    assert isinstance(metric, CycleMetric)
    assert metric.duration_seconds == 0.12
    assert metric.is_delayed is False
    assert tracker.total_cycles == 1
    assert tracker.last_cycle_duration_seconds == 0.12
    assert tracker.min_duration_seconds == 0.12
    assert tracker.max_duration_seconds == 0.12
    assert tracker.avg_duration_seconds == 0.12


def test_cycle_latency_tracker_delayed_detection():
    delayed_alerts = []

    def on_delayed(m: CycleMetric):
        delayed_alerts.append(m)

    tracker = CycleLatencyTracker(
        name="exit_loop_tracker",
        warn_threshold_seconds=0.1,
        on_delayed_cycle=on_delayed,
    )

    # Ciclo normal
    tracker.record_cycle(0.05)
    assert tracker.delayed_cycles_count == 0
    assert len(delayed_alerts) == 0

    # Ciclo com latência inflada (> 0.1s)
    m2 = tracker.record_cycle(0.25)
    assert m2.is_delayed is True
    assert tracker.delayed_cycles_count == 1
    assert len(delayed_alerts) == 1
    assert delayed_alerts[0].duration_seconds == 0.25

    snap = tracker.snapshot()
    assert snap["is_currently_delayed"] is True
    assert snap["delayed_cycles_count"] == 1
    assert snap["total_cycles"] == 2


def test_cycle_latency_tracker_sync_context_manager():
    tracker = CycleLatencyTracker(name="sync_loop", warn_threshold_seconds=1.0)
    with tracker.measure(details={"ticker": "PETR4"}):
        time.sleep(0.02)

    assert tracker.total_cycles == 1
    assert tracker.last_cycle_duration_seconds >= 0.015
    snap = tracker.snapshot()
    assert snap["total_cycles"] == 1


@pytest.mark.asyncio
async def test_cycle_latency_tracker_async_context_manager():
    tracker = CycleLatencyTracker(name="async_loop", warn_threshold_seconds=1.0)
    async with tracker.measure_async(details={"step": "market_scan"}):
        await asyncio.sleep(0.02)

    assert tracker.total_cycles == 1
    assert tracker.last_cycle_duration_seconds >= 0.015


def test_cycle_latency_tracker_history_bounding():
    tracker = CycleLatencyTracker(name="bounded", max_history=5)
    for i in range(10):
        tracker.record_cycle(float(i))

    assert tracker.total_cycles == 10
    assert len(tracker._history) == 5
    assert tracker.min_duration_seconds == 0.0
    assert tracker.max_duration_seconds == 9.0
