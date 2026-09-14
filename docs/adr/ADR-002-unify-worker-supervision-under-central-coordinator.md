# ADR-002: Unificação da Supervisão de Background Workers sob o `CentralCoordinator`

- **Status**: Proposto (Submetido para ratificação institucional)
- **Data**: 2026-09-14
- **Autoridade Responsável**: NEXUS CSOO (Operações e Orquestração)
- **Decisores**: Victor (Fundador), CEO Astra, NEXUS CSOO, Antigravity, Sentinel
- **Escopo**: `trading_bot/core/coordinator.py`, `backend/app/main.py`, `backend/app/worker_state.py`, `trading_bot/infra/health_monitor.py`
- **Classificação**: Resiliência / Concorrência Assíncrona / Ciclo de Vida de Processos

---

## 1. Contexto e Formulação do Problema

A integridade operacional de uma plataforma de trading algorítmico depende de supervisão robusta de processos assíncronos. Processos zumbis, laços infinitos não supervisionados ou falhas silenciosas de corrotinas podem resultar em exposição financeira descontrolada ou ordens não canceladas.

O ecossistema Meridian implementou uma infraestrutura avançada de orquestração assíncrona denominada `CentralCoordinator` (`trading_bot/core/coordinator.py`), concebida para:
- Supervisionar ciclos de execução com watchdog ativo contra travamentos (*deadlocks*).
- Aplicar política institucional de reinicialização com backoff exponencial ($2^{\text{retry}-1} \le 30\,\text{s}$) e limite estrito de 5 falhas consecutivas.
- Emitir trilha imutável de telemetria baseada em eventos estruturados (`WorkerEvent`).
- Acionar salvaguardas *fail-closed* imediatas (`on_exhausted` aciona bloqueio permanente via `exit_gate_sticky_block`).

### 1.1. A Dualidade Crítica Diagnosticada
A auditoria empírica de código identificou que, em vez de operar sob um único motor de supervisão, o sistema opera sob **duas arquiteturas paralelas e concorrentes**:

1. **Supervisores Manuais Legados em `backend/app/main.py`**:
   - `worker_supervisor()` (linha 766) supervisiona o laço de análise e comitê (`ai_committee_worker`).
   - `exit_loop_supervisor()` (linha 804) supervisiona o laço de saída de posições (`exit_loop`).
   - Esses laços utilizam laços `while True` rudimentares, atualizam contadores voláteis no singleton `backend.app.worker_state.state` e tratam exceções de forma isolada.

2. **O Motor Institucional `CentralCoordinator` (`trading_bot/core/coordinator.py`)**:
   - Implementa registro formal de workers (`ManagedWorker`), monitoramento de liveness com timeout de heartbeat, cálculo de atraso de backoff e disparos de alertas.

3. **O Conflito Estrutural no `lifespan` do FastAPI (`backend/app/main.py:33-66`)**:
   ```python
   # Trecho real auditado em backend/app/main.py:
   coord = CentralCoordinator()
   coord.register_worker("ai_worker", lambda: ai_committee_worker(...), interval_seconds=60)
   coord.register_worker("exit_loop", lambda: exit_loop(...), interval_seconds=5)
   app.state.coordinator = coord
   # ANOMALIA: A chamada await coord.start() NUNCA é invocada!
   # Em vez disso, disparam-se os supervisores legados:
   task = asyncio.create_task(worker_supervisor())
   exit_task = asyncio.create_task(exit_loop_supervisor())
   ```
   **Diagnóstico**: O `CentralCoordinator` é instanciado na memória da aplicação web, recebe o registro dos workers, mas **permanece eternamente em estado ocioso (`STOPPED`)**. A aplicação FastAPI executa os supervisores legados em background.

4. **Divergência entre Ambientes CLI e API**:
   - Quando o sistema é executado via script autônomo (`scripts/run_coordinator.py`), ele inicializa e executa o `CentralCoordinator`.
   - Quando o sistema roda como servidor HTTP via Uvicorn (`backend/app/main.py`), ele executa os supervisores legados.
   - Isso gera disparidade de comportamento operacional entre o ambiente de testes/CLI e o ambiente de produção web.

---

## 2. Drivers de Decisão (Decision Drivers)

1. **Fonte Única de Supervisão**: Eliminar supervisores ad-hoc legados e estabelecer um único ponto de supervisão de processos no ecossistema.
2. **Consistência Operacional e de Auditoria**: Garantir que o comportamento de falha, backoff e emissão de eventos seja idêntico, quer o sistema seja executado via FastAPI ou como daemon CLI independente.
3. **Observabilidade Unificada**: Concentrar o estado de saúde de todas as tarefas assíncronas em uma estrutura de dados inspecionável por telemetria e endpoints de status.
4. **Integração de Métricas de Infraestrutura**: Acoplar o monitor de integridade de recursos do sistema (`OperationalHealthMonitor`) ao ciclo de watchdog do coordenador central.

---

## 3. Opções Consideradas

### Opção A: Manter os Supervisores Legados e Descartar o `CentralCoordinator`
- *Vantagens*: Código simples e direto dentro de `main.py`.
- *Desvantagens*: Perde watchdog de travamento, telemetria de eventos, limites globais de reinicialização institucional e causa divergência com os scripts headless de coordenação.

### Opção B: Manter Ambos com Coordenação Híbrida
- *Vantagens*: Nenhuma modificação necessária a curto prazo.
- *Desvantagens*: Confusão arquitetural permanente, desperdício de memória e risco de operadores consultarem o estado inativo em `app.state.coordinator` achando que reflete a saúde dos workers.

### Opção C (Escolhida): Promover o `CentralCoordinator` como Autoridade Única de Supervisão
- *Vantagens*: Padronização institucional, controle estrito de ciclo de vida no startup/shutdown do FastAPI, observabilidade completa e fail-closed garantido.
- *Desvantagens*: Requer refatoração do `lifespan` de `main.py` e eliminação segura das funções legadas `worker_supervisor` e `exit_loop_supervisor`.

---

## 4. Decisão Arquitetural

Adota-se formalmente a **Opção C**. O `CentralCoordinator` torna-se a **única autoridade de supervisão e orquestração de workers assíncronos** do Meridian.

### 4.1. Refatoração do Ciclo de Vida (`lifespan`) em `backend/app/main.py`
O ciclo de vida assíncrono da aplicação FastAPI será refatorado para delegar a gestão integral das tarefas ao `CentralCoordinator`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Validação de segurança e configuração (fail-fast)
    validate_security_config()
    
    # 2. Inicialização e injeção de dependências no Coordenador
    coord = CentralCoordinator()
    
    # Registro dos workers institucionais
    coord.register_worker(
        name="ai_worker",
        coro_fn=ai_committee_worker_iteration,
        interval_seconds=60,
        max_restarts=5,
        backoff_base=2.0,
        max_backoff_seconds=30.0,
        on_exhausted=on_worker_exhausted_fail_closed,
    )
    coord.register_worker(
        name="exit_loop",
        coro_fn=exit_loop_iteration,
        interval_seconds=5,
        max_restarts=5,
        backoff_base=2.0,
        max_backoff_seconds=30.0,
        on_exhausted=on_worker_exhausted_fail_closed,
    )
    
    # Início formal da supervisão assíncrona
    await coord.start()
    app.state.coordinator = coord
    
    yield
    
    # Desligamento gracioso (graceful shutdown)
    logger.info("Encerrando supervisão do CentralCoordinator...")
    await coord.stop(timeout=10.0)
```

### 4.2. Descomissionamento dos Supervisores Legados
As funções `worker_supervisor()` (linha 766) e `exit_loop_supervisor()` (linha 804) de `backend/app/main.py` serão marcadas como obsoletas e removidas. Seus laços internos serão transformados em corrotinas de iteração unitária (`ai_committee_worker_iteration`, `exit_loop_iteration`), recebendo o tempo de espera e o controle de exceção diretamente do `CentralCoordinator`.

### 4.3. Integração com o `OperationalHealthMonitor`
O monitor de recursos nativo do Windows (`trading_bot/infra/health_monitor.py`) será registrado como worker de diagnóstico periódico (`health_monitor_worker`, intervalo de 30 segundos) no `CentralCoordinator`. Se a memória disponível for inferior a 500 MB ou o uso exceder 95%, o coordenador sinalizará estado crítico e pausará o worker de compras (`ai_worker`).

### 4.4. Exposição de Telemetria no Endpoint `/api/coordinator/status`
A rota `/api/status` e um novo endpoint `/api/coordinator/status` consultarão diretamente `coord.get_status()`, retornando:
- Estado do ciclo de vida (`RUNNING`, `DEGRADED`, `STOPPED`).
- Contadores de reinicialização e timestamps de último batimento cardíaco (*heartbeat*) por worker.
- Log estruturado dos últimos 50 eventos (`WorkerEvent`).

---

## 5. Consequências

### 5.1. Consequências Positivas
- **Unificação Comportamental**: O comportamento de resiliência e auto-recuperação passa a ser 100% idêntico entre a execução da API e a execução de daemons de linha de comando.
- **Fail-Closed Robusto**: Quando um worker esgota suas 5 tentativas de reinicialização, o callback `on_exhausted` ativa `exit_gate_sticky_block = True`, impedindo novas ordens e mantendo a salvaguarda financeira institucional.
- **Transparência Operacional**: Fim do estado "fantasma" onde o coordenador existia em `app.state` sem estar rodando.
- **Limpeza de Código**: Eliminação de mais de 120 linhas de código boilerplate duplicado de laços de supervisão em `backend/app/main.py`.

### 5.2. Consequências Negativas e Mitigações
- **Necessidade de Adequação de Testes Legados**: Testes que injetavam falhas inspecionando diretamente `backend.app.worker_state.state` precisarão inspecionar os eventos em `coord.get_events()`.
  - *Mitigação*: Manter sincronização bidirecional entre `CoordinatorWorkerState` e `worker_state.state` durante um ciclo de depreciação.

---

## 6. Governança e Critérios de Aceite

1. `await coord.start()` é explicitamente chamado no `lifespan` de `main.py` e verificado via teste unitário de inicialização assíncrona.
2. Nenhuma menção a `worker_supervisor()` ou `exit_loop_supervisor()` permanece em `backend/app/main.py`.
3. Injeção determinística de falhas comprova que após 5 quedas seguidas o coordenador entra em estado `EXHAUSTED` e ativa o bloqueio institucional `exit_gate_sticky_block`.
4. Todos os 822+ testes unitários e de integração existentes continuam passando sem quebra de contrato.
