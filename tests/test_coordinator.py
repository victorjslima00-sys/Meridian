"""
Testes do Coordenador Central de Workers Assíncronos e Supervisão de Resiliência (P2).

Cobre:
- Registro de workers e rejeição de nomes duplicados;
- Início e parada graciosa (graceful shutdown) de workers múltiplos;
- Captura de falhas com contabilidade de crash e backoff exponencial isolado;
- Esgotamento de restarts (MAX_RESTARTS) com transição para 'stopped' e callback de emergência;
- Monitoramento de heartbeat e alertas do watchdog para workers travados;
- Snapshot de integridade, journal de eventos auditável e garantia de zero envio real.
"""
import asyncio
import datetime
from unittest.mock import MagicMock, patch

import pytest

from trading_bot.core.coordinator import CentralCoordinator, ManagedWorker, WorkerEvent
from backend.app.worker_state import LoopSupervisionState


@pytest.fixture
def coordinator():
    return CentralCoordinator(heartbeat_timeout_seconds=5.0, watchdog_interval_seconds=0.1)


def test_coordinator_registration(coordinator):
    async def dummy_worker():
        pass

    w = coordinator.register_worker(
        name="test_worker_1",
        coro_fn=dummy_worker,
        interval_seconds=10.0,
        max_restarts=3,
        is_critical=True,
    )
    assert w.name == "test_worker_1"
    assert w.is_critical is True
    assert coordinator.get_worker("test_worker_1") is w

    # Rejeição de duplicata
    with pytest.raises(ValueError, match="já registrado"):
        coordinator.register_worker(name="test_worker_1", coro_fn=dummy_worker)


@pytest.mark.asyncio
async def test_coordinator_lifecycle_clean_shutdown(coordinator):
    started = []
    cancelled = []

    async def persistent_worker():
        started.append(True)
        try:
            while True:
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    coordinator.register_worker("persistent_1", persistent_worker)
    assert coordinator.is_running is False

    await coordinator.start()
    assert coordinator.is_running is True
    await asyncio.sleep(0.05)

    assert len(started) == 1

    await coordinator.stop()
    assert coordinator.is_running is False
    assert len(cancelled) == 1

    snap = coordinator.snapshot()
    assert snap["coordinator_running"] is False
    assert snap["workers"]["persistent_1"]["status"] == "stopped"


@pytest.mark.asyncio
async def test_coordinator_worker_crash_and_restart(coordinator):
    crashes = {"count": 0}
    delays = []

    async def flaky_worker():
        crashes["count"] += 1
        if crashes["count"] <= 2:
            raise RuntimeError(f"Crash transitório #{crashes['count']}")
        return  # 3ª iteração tem sucesso e completa

    async def fake_sleep(d):
        delays.append(d)

    alerts = []

    def mock_alert(msg: str):
        alerts.append(msg)

    w = coordinator.register_worker(
        name="flaky_worker",
        coro_fn=flaky_worker,
        max_restarts=5,
        backoff_cap_seconds=30.0,
        alert_fn=mock_alert,
    )

    with patch("trading_bot.core.coordinator.asyncio.sleep", side_effect=fake_sleep):
        coordinator._is_running = True
        await coordinator._run_worker_supervisor(w)

    assert crashes["count"] == 3
    assert w.supervision.restart_count == 2
    assert delays == [1, 2]
    assert len(alerts) == 2


@pytest.mark.asyncio
async def test_coordinator_worker_exhausts_restarts_triggers_hook(coordinator):
    delays = []
    hook_called = []
    alerts = []

    async def always_fails():
        raise RuntimeError("Falha fatal e persistente")

    async def fake_sleep(d):
        delays.append(d)

    def on_exhausted_callback():
        hook_called.append("triggered")

    def alert_callback(msg: str):
        alerts.append(msg)

    w = coordinator.register_worker(
        name="critical_exit_worker",
        coro_fn=always_fails,
        max_restarts=3,
        backoff_cap_seconds=10.0,
        is_critical=True,
        on_exhausted=on_exhausted_callback,
        alert_fn=alert_callback,
    )

    with patch("trading_bot.core.coordinator.asyncio.sleep", side_effect=fake_sleep):
        coordinator._is_running = True
        await coordinator._run_worker_supervisor(w)

    assert w.supervision.status == "stopped"
    assert w.supervision.restart_count == 4  # 3 restarts permitidos + 1 que esgotou
    assert hook_called == ["triggered"]
    assert any("PARADO" in a for a in alerts)

    # Verifica snapshot após exaustão
    snap = coordinator.snapshot()
    assert snap["global_status"] == "stopped"
    assert snap["fail_closed_guarantee"] is True
    assert snap["real_broker_calls"] == 0


@pytest.mark.asyncio
async def test_coordinator_watchdog_detects_stale_heartbeat(coordinator):
    async def hung_worker():
        while True:
            await asyncio.sleep(0.01)

    w = coordinator.register_worker("hung_worker", hung_worker)
    w.supervision.status = "running"
    w.last_activity_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)

    # Executa watchdog probe
    await coordinator._watchdog_loop() if False else None  # syntax check

    events_before = len(coordinator.get_events())
    # Simula passagem de 1 ciclo do watchdog
    coordinator._is_running = True
    watchdog_task = asyncio.create_task(coordinator._watchdog_loop())
    await asyncio.sleep(0.15)
    coordinator._is_running = False
    watchdog_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watchdog_task

    events = coordinator.get_events()
    watchdog_alerts = [e for e in events if e["event_type"] == "WATCHDOG_ALERT"]
    assert len(watchdog_alerts) >= 1
    assert "heartbeat estagnado" in watchdog_alerts[0]["message"]


def test_coordinator_snapshot_structure(coordinator):
    snap = coordinator.snapshot()
    assert "coordinator_running" in snap
    assert "global_status" in snap
    assert "workers" in snap
    assert "recent_events" in snap
    assert snap["real_broker_calls"] == 0


def test_scheduler_coordinator_binding(coordinator):
    from trading_bot.core.scheduler import Scheduler
    sched = Scheduler()
    assert sched.coordinator is None

    sched.bind_coordinator(coordinator)
    assert sched.coordinator is coordinator

    async def sample_coro():
        pass

    sched.add_async_job("async_sample", sample_coro, interval_seconds=42.0)
    w = coordinator.get_worker("async_sample")
    assert w is not None
    assert w.interval_seconds == 42.0
