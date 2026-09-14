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


@pytest.mark.asyncio
async def test_mark_active_keeps_worker_alive():
    """Garante que mark_active() mantém o worker vivo e evita falso-negativo na inicialização."""
    coord = CentralCoordinator(heartbeat_timeout_seconds=2.0, watchdog_interval_seconds=0.05)
    
    cycle_counter = {"cycles": 0}

    async def active_worker():
        while True:
            cycle_counter["cycles"] += 1
            await asyncio.sleep(0.02)

    w = coord.register_worker("active_worker_1", active_worker)
    
    # Inicialização: tarefa ainda não iniciou, mas não deve avaliar como vivo sem task
    assert w.is_alive() is False
    
    await coord.start()
    try:
        # Logo após o start, worker foi iniciado e está em running
        assert w.is_alive() is True
        assert w.last_activity_at is not None

        # Registra atividade explícita via coordenador
        first_act = w.last_activity_at
        await asyncio.sleep(0.05)
        coord.mark_active("active_worker_1")
        assert w.last_activity_at > first_act
        assert w.consecutive_stale_checks == 0
        assert w.is_alive() is True

        # Simula atraso superior ao timeout de heartbeat
        w.last_activity_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=5.0)
        assert w.is_alive(timeout_seconds=2.0) is False

        # Invocação de mark_active reativa o worker
        w.mark_active()
        assert w.is_alive(timeout_seconds=2.0) is True
        assert w.consecutive_stale_checks == 0
    finally:
        await coord.stop()


@pytest.mark.asyncio
async def test_watchdog_auto_heals_frozen_task():
    """
    Verifica que o watchdog detecta tarefa congelada, executa remediação ativa
    (cancelando a task e alertando) e auto-recupera (auto-heal) o worker.
    """
    coord = CentralCoordinator(
        heartbeat_timeout_seconds=0.1,
        watchdog_interval_seconds=0.05,
        stale_threshold=2,
    )
    
    alerts = []

    def mock_alert(msg: str):
        alerts.append(msg)

    hung_task_started = asyncio.Event()

    async def hung_worker():
        hung_task_started.set()
        # Simula travamento absoluto que para de responder
        while True:
            await asyncio.sleep(10.0)

    w = coord.register_worker(
        "hung_remediate_worker",
        hung_worker,
        max_restarts=3,
        alert_fn=mock_alert,
    )

    await coord.start()
    try:
        await hung_task_started.wait()
        original_task = w.supervisor_task
        assert original_task is not None
        assert not original_task.done()

        # Envelhece artificialmente o last_activity_at para disparar stale checks
        w.last_activity_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1.0)

        # Aguarda o watchdog realizar checagens e atingir stale_threshold (2 checagens)
        for _ in range(25):
            await asyncio.sleep(0.05)
            events = coord.get_events()
            if any(e["event_type"] == "WATCHDOG_AUTOHEAL" for e in events):
                break

        events = coord.get_events()
        event_types = [e["event_type"] for e in events]
        assert "WATCHDOG_ALERT" in event_types
        assert "WATCHDOG_REMEDIATION" in event_types
        assert "WATCHDOG_AUTOHEAL" in event_types

        # Verifica alerta de remediação enviado
        assert any("Watchdog Remediation" in a for a in alerts)

        # Verifica que a task original foi cancelada e substituída por uma nova
        assert original_task.done() or original_task.cancelled()
        assert w.supervisor_task is not original_task
        assert not w.supervisor_task.done()
        assert w.is_alive() is True
    finally:
        await coord.stop()


def test_coordinator_health_monitor_integration_non_synthetic():
    """Verifica que o coordinator expõe métricas reais do SO via OperationalHealthMonitor sem constantes sintéticas."""
    coord = CentralCoordinator()
    snap = coord.snapshot()

    assert "system_health" in snap
    health = snap["system_health"]
    assert health is not None
    assert "ram_total_mb" in health
    assert "disk_free_gb" in health
    assert "cpu_cores" in health
    assert health["ram_total_mb"] > 0
    assert health["disk_free_gb"] > 0
    assert health["cpu_cores"] > 0
    assert "system_status" in health
    assert health["system_status"] in ("HEALTHY", "WARNING_LOW_DISK", "CRITICAL_LOW_MEMORY")


def test_managed_worker_activity_callback_auto_binding():
    """Garante que a supervision registra e propaga callback de atividade automaticamente."""
    from backend.app.worker_state import LoopSupervisionState
    sup = LoopSupervisionState()
    
    async def dummy():
        pass

    coord = CentralCoordinator()
    w = coord.register_worker("callback_worker", dummy, supervision=sup)
    assert sup.activity_callback is not None

    w.consecutive_stale_checks = 5
    sup.mark_cycle_complete()
    assert w.consecutive_stale_checks == 0
    assert w.last_activity_at is not None

