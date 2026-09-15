"""
Tripwire e teste de guarda arquitetural para o Coordenador Central e Supervisores Legados (WS-A).

Garante que:
1. O runtime de produção (backend/app/main.py) NÃO chama `await coord.start()`,
   evitando duplicação de execução de workers em paralelo com supervisores legados;
2. O auto-healing do CentralCoordinator é categorizado como IMPLEMENTED BUT NOT WIRED
   no runtime atual;
3. O CentralCoordinator em app.state.coordinator permanece desacoplado para observabilidade,
   com `is_running == False` e sem watchdog task ativo no startup.
"""
import ast
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def test_main_py_does_not_call_coord_start():
    """Garante via AST estática que backend/app/main.py não contém chamadas a coord.start()."""
    main_file = Path(__file__).resolve().parent.parent / "backend" / "app" / "main.py"
    assert main_file.exists(), f"Arquivo não encontrado: {main_file}"

    tree = ast.parse(main_file.read_text(encoding="utf-8"), filename=str(main_file))
    
    start_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "start":
                # Verifica se o objeto chamado é coord ou app.state.coordinator
                if isinstance(func.value, ast.Name) and func.value.id == "coord":
                    start_calls.append(f"coord.start() na linha {node.lineno}")
                elif isinstance(func.value, ast.Attribute) and func.value.attr == "coordinator":
                    start_calls.append(f"coordinator.start() na linha {node.lineno}")

    assert not start_calls, (
        f"VIOLAÇÃO DE ARQUITETURA (WS-A): Chamada a coord.start() detectada no runtime atual: {start_calls}. "
        "Isso causaria duplicação catastrófica de workers com os supervisores legados!"
    )


@pytest.mark.asyncio
async def test_lifespan_leaves_coordinator_unstarted_and_watchdog_unwired():
    """Garante que a execução do lifespan do FastAPI não inicia a supervisão do CentralCoordinator."""
    from backend.app.main import app, lifespan
    
    # Mock das dependências internas importadas no início do lifespan
    with patch("backend.app.security.validate_security_config"), \
         patch("backend.app.runtime_config.RuntimeConfig.load"), \
         patch("backend.app.data.database.init_db"), \
         patch("trading_bot.risk.circuit_breaker.CircuitBreaker.from_config"), \
         patch("backend.app.main.worker_supervisor", new_callable=AsyncMock) as mock_worker_sup, \
         patch("backend.app.main.exit_loop_supervisor", new_callable=AsyncMock) as mock_exit_sup:
         
        # Dispara o lifespan de forma assíncrona controlada
        async with lifespan(app):
            # 1. Verifica que app.state.coordinator foi criado para observabilidade
            assert hasattr(app.state, "coordinator"), "app.state.coordinator deve estar presente"
            coord = app.state.coordinator
            assert coord is not None
            
            # 2. PROVA CRÍTICA: o coordinator NÃO foi iniciado
            assert coord.is_running is False, (
                "coord.is_running DEVE ser False no runtime atual para evitar duplicação"
            )
            assert coord._watchdog_task is None, (
                "Watchdog task de auto-healing DEVE ser None (IMPLEMENTED BUT NOT WIRED)"
            )
            for w_name, worker in coord._workers.items():
                assert worker.supervisor_task is None, (
                    f"Worker '{w_name}' supervisor_task DEVE ser None (coordenador não deve ter iniciado)"
                )
            
            # 3. Snapshot reflete coordenador parado e auto-healing inativo
            snap = coord.snapshot()
            assert snap["coordinator_running"] is False
            
            # 4. Verifica que os supervisores legados foram agendados no startup
            assert app.state.worker_task is not None
            assert app.state.exit_task is not None


def test_autohealing_status_documentation():
    """Garante que a documentação de migração existe no repositório e define auto-healing como NOT WIRED."""
    doc_path = Path(__file__).resolve().parent.parent / "docs" / "architecture" / "CENTRAL_COORDINATOR_MIGRATION.md"
    assert doc_path.exists(), f"Documento mandatório não encontrado: {doc_path}"
    
    content = doc_path.read_text(encoding="utf-8")
    assert "IMPLEMENTED BUT NOT WIRED INTO CURRENT RUNTIME" in content
    assert "duplicate-worker risk" in content.lower() or "duplicate worker" in content.lower()
    assert "registration != execution" in content.lower() or "registration is decoupled" in content.lower()
