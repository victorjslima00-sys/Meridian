#!/usr/bin/env python3
"""
Executável do Coordenador Central de Workers Assíncronos (P2).

Permite a execução autônoma e supervisionada dos workers de background
(ai_committee_worker, exit_loop, tasks periódicas) em ambiente headless,
com shutdown gracioso via sinais (SIGINT/SIGTERM), monitoramento de
heartbeat ativo e salvaguarda fail-closed estrita (real_broker_calls == 0).

Uso:
    python scripts/run_coordinator.py [--duration SECONDS] [--dry-run] [--mode paper_trading]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

# Adiciona o diretório raiz ao path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from trading_bot.core.coordinator import CentralCoordinator
from backend.app import worker_state
from backend.app.data.database import init_db
from backend.app.runtime_config import RuntimeConfig
from backend.app.security import validate_security_config
from trading_bot.risk.circuit_breaker import CircuitBreaker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("MeridianCoordinator")


async def main_async(args: argparse.Namespace) -> int:
    print("=" * 70)
    print("  MERIDIAN TECHNOLOGIES — COORDENADOR CENTRAL DE WORKERS (P2)")
    print("  Status: Standalone Headless Supervision Daemon")
    print(f"  Modo Operacional: {args.mode}")
    print("  Garantia de Execução: ZERO CHAMADAS REAIS (real_broker_calls == 0)")
    print("=" * 70)

    # 1. Validações fail-fast de segurança e dados
    validate_security_config()
    RuntimeConfig.load()
    init_db()
    CircuitBreaker.from_config()

    # 2. Inicialização do Coordenador Central
    coordinator = CentralCoordinator(
        heartbeat_timeout_seconds=args.heartbeat_timeout,
        watchdog_interval_seconds=args.watchdog_interval,
    )

    # Importa os loops do backend
    from backend.app.main import ai_committee_worker, exit_loop, _alerta_telegram

    # 3. Registra os workers essenciais
    coordinator.register_worker(
        name="ai_committee_worker",
        coro_fn=ai_committee_worker,
        interval_seconds=worker_state.SCAN_INTERVAL_SECONDS,
        max_restarts=worker_state.MAX_RESTARTS,
        backoff_cap_seconds=worker_state.BACKOFF_CAP_SECONDS,
        is_critical=False,
        supervision=worker_state.state,
        alert_fn=_alerta_telegram,
    )

    coordinator.register_worker(
        name="exit_loop",
        coro_fn=exit_loop,
        interval_seconds=worker_state.EXIT_INTERVAL_SECONDS,
        max_restarts=worker_state.MAX_RESTARTS,
        backoff_cap_seconds=worker_state.BACKOFF_CAP_SECONDS,
        is_critical=True,
        on_exhausted=worker_state.state.set_exit_gate_sticky_block,
        supervision=worker_state.state.exit_supervision,
        alert_fn=_alerta_telegram,
    )

    if args.dry_run:
        print("\n[DRY RUN] Coordenador configurado com sucesso.")
        snap = coordinator.snapshot()
        print(f"[DRY RUN] Workers registrados: {list(snap['workers'].keys())}")
        print(f"[DRY RUN] Status global: {snap['global_status']}")
        print("[DRY RUN] Validação estrita concluída. Encerrando sem erros (código 0).")
        return 0

    stop_event = asyncio.Event()

    def _handle_signal():
        logger.info("Sinal de interrupção recebido. Iniciando shutdown gracioso...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Tratamento no Windows para sinais assíncronos
            pass

    logger.info("Iniciando workers sob supervisão do CentralCoordinator...")
    await coordinator.start()

    try:
        if args.duration:
            logger.info("Executando com duração programada de %s segundos...", args.duration)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=args.duration)
            except asyncio.TimeoutError:
                logger.info("Duração programada (%ss) expirada.", args.duration)
        else:
            logger.info("Coordenador em execução contínua. Pressione Ctrl+C para encerrar.")
            await stop_event.wait()
    finally:
        logger.info("Encerrando Coordenador Central e todas as tasks...")
        await coordinator.stop()
        snap = coordinator.snapshot()
        print("\n" + "=" * 70)
        print("  RELATÓRIO DE ENCERRAMENTO DO COORDENADOR")
        print(f"  Status Final: {snap['global_status']}")
        print(f"  Workers Coordenados: {snap['registered_workers_count']}")
        for w_name, w_info in snap["workers"].items():
            print(f"    - {w_name}: status={w_info['status']}, restarts={w_info['restart_count']}")
        print("=" * 70)

    return 0


def main():
    parser = argparse.ArgumentParser(description="Coordenador Central de Workers Meridian")
    parser.add_argument("--duration", type=float, default=None, help="Duração máxima em segundos antes de parar")
    parser.add_argument("--dry-run", action="store_true", help="Valida registro e encerra sem subir loops infinitos")
    parser.add_argument("--mode", default="paper_trading", help="Modo operacional (paper_trading)")
    parser.add_argument("--heartbeat-timeout", type=float, default=300.0, help="Timeout de heartbeat (s)")
    parser.add_argument("--watchdog-interval", type=float, default=15.0, help="Intervalo de checagem do watchdog (s)")
    args = parser.parse_args()

    try:
        exit_code = asyncio.run(main_async(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupção manual pelo operador. Finalizando.")
        sys.exit(0)


if __name__ == "__main__":
    main()
