# Registro Geral de Dívida Técnica (Technical Debt Register) — Meridian

- **Protocolo Institucional**: `MERIDIAN-TECH-DEBT-20260914-WS-D`
- **Data da Emissão**: 2026-09-14
- **Branch de Governança**: `team/architecture-audit`
- **Autoridade Responsável**: NEXUS CSOO / SENTINEL / ANTIGRAVITY
- **Classificação**: Registro Formal de Riscos Arquiteturais e Roadmap de Engenharia

---

## 1. Sumário e Matriz de Riscos de Dívida Técnica

Este documento consolida o inventário exaustivo de débitos técnicos identificados durante a auditoria arquitetural do repositório Meridian. Embora o sistema demonstre alta conformidade com as salvaguardas financeiras primárias (`real_broker_calls == 0`, integridade SHA-256 e fail-closed em dados ausentes), a coexistência de abstrações legadas e acoplamentos estruturais introduz fricções operacionais e riscos de manutenção.

### Matriz de Severidade e Priorização

| ID | Subsistema | Título da Dívida Técnica | Severidade | Raio de Impacto (Blast Radius) | ADR Relacionado | Fase Roadmap |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **TD-001** | Arquitetura Geral | Acoplamento Circular Invertido (`trading_bot` $\longrightarrow$ `backend.app`) | **ALTO** | Amplo (Todo o núcleo quantitativo) | ADR-001 | Fase 3 |
| **TD-002** | Coordenação / Workers | Supervisão Duplicada de Background Workers (FastAPI vs Coordenador) | **ALTO** | Crítico (Ciclo de vida de execução) | ADR-002 | Fase 2 |
| **TD-003** | Execução / Broker | Fragmentação de 5 Modelos de Ordem e Abstrações de Corretora | **ALTO** | Amplo (Gestão de ordens e custódia) | ADR-003 | Fase 4 |
| **TD-004** | Execução / Risco | Disparidade Contábil de Custos B3 (Fricção 10 bps ausente no Paper) | **ALTO** | Crítico (Integridade contábil do PnL) | ADR-003 | Fase 4 |
| **TD-005** | Governança de Risco | Desconexão da Governança de Correlação B3 (Lista estática BTC/ETH) | **ALTO** | Médio (Gestão de risco pré-trade) | ADR-004 | Fase 1 |
| **TD-006** | Configuração | Configurações Fantasma e Falta de Schema Pydantic Estrito | **MÉDIO** | Médio (Operações e setup) | ADR-005 | Fase 1 |
| **TD-007** | DevOps / Deploy | Conflito de Concorrência de Banco no `docker-compose.yml` | **ALTO** | Alto (Contenção SQLite em prod) | ADR-003 | Fase 4 |
| **TD-008** | Pesquisa Quantitativa| 10 Módulos Matemáticos Avançados Desconectados da Operação | **BAIXO** | Local (`trading_bot/data/quant/`) | — | Fase 5 |
| **TD-009** | Camada Web / API | Monólito de 1.412 Linhas em `backend/app/main.py` | **MÉDIO** | Médio (Manutenibilidade da API) | ADR-002 | Fase 2 |
| **TD-010** | Ingestão de Dados | Cache de Cotações In-Memory não Compartilhado com Scraping Direto | **MÉDIO** | Médio (Resiliência de feeds) | — | Fase 3 |

---

## 2. Inventário Exaustivo de Débitos Técnicos

---

### TD-001: Acoplamento Circular Invertido (`trading_bot` $\longrightarrow$ `backend.app`)
- **Subsistema**: Arquitetura Geral / Núcleo Quantitativo
- **Severidade**: **ALTO**
- **Raio de Impacto**: Todo o ecossistema `trading_bot/` e inicialização do `backend/app/`
- **Causa Raiz**: O pacote `trading_bot` foi originalmente concebido como uma biblioteca autocontida. Com a evolução rápida do projeto, módulos internos passaram a importar diretamente do banco relacional do backend (`backend.app.data.database`) e de agentes de serviço (`backend.app.agents.*`).
- **Evidências no Código**:
  * `trading_bot/core/coordinator.py:28` importa `now_b3` de `backend.app.data.database`.
  * `trading_bot/core/coordinator.py:67` importa `LoopSupervisionState` de `backend.app.worker_state`.
  * `trading_bot/risk/circuit_breaker.py:111` realiza lazy import de `compute_current_equity` e `get_equity_refs`.
  * `trading_bot/data/valuation_snapshot.py:111` realiza lazy import de `get_current_price` de `backend.app.data.feed`.
  * `trading_bot/execution/paper_session.py:27-29` importa `ExecutorAgent`, `RiskManager` e `DB_PATH`.
- **Risco Operacional e Financeiro**:
  * Falhas de inicialização cíclica (*circular import errors*) mascaradas por lazy imports.
  * Impossibilidade de extrair `trading_bot` como pacote autônomo (pip / wheel) para execução isolada em containers leves de execução rápida ou Lambdas.
- **Estratégia de Remediação**:
  * Executar as diretrizes do **ADR-001**: migrar funções neutras para `trading_bot/core/clock.py`, definir interfaces `Protocol` e injetar instâncias de dados no `CircuitBreaker` e `CentralCoordinator` via inversão de controle.
- **Esforço Estimado**: 8 horas-homem.
- **Dependências**: Nenhuma prévia.

---

### TD-002: Supervisão Duplicada de Background Workers
- **Subsistema**: Coordenação / Ciclo de Vida Assíncrono
- **Severidade**: **ALTO**
- **Raio de Impacto**: Estabilidade de execução contínua da API FastAPI e dos workers em background
- **Causa Raiz**: Criação de um coordenador avançado (`CentralCoordinator`) sem o subsequente descomissionamento das corrotinas legadas de supervisão criadas nas primeiras versões da API.
- **Evidências no Código**:
  * `backend/app/main.py:33-40`: O `lifespan` instancia `CentralCoordinator` e registra os workers, mas nunca chama `await coord.start()`.
  * `backend/app/main.py:42-43`: Linhas disparam explicitamente tarefas manuais `asyncio.create_task(worker_supervisor())` e `asyncio.create_task(exit_loop_supervisor())`.
  * `backend/app/main.py:766-830`: Declaração dos supervisores manuais com loops `while True` e contadores globais.
- **Risco Operacional e Financeiro**:
  * O coordenador central permanece ocioso na memória em produção.
  * Falhas sucessivas dos laços não disparam o watchdog formal nem o callback institucional `on_exhausted` (que acionaria o `exit_gate_sticky_block`), mantendo um risco de comportamento não fail-closed em produção contínua.
- **Estratégia de Remediação**:
  * Executar as diretrizes do **ADR-002**: acionar `await app.state.coordinator.start()` no `lifespan` do FastAPI e remover as funções legadas `worker_supervisor` e `exit_loop_supervisor`.
- **Esforço Estimado**: 6 horas-homem.
- **Dependências**: TD-001 (desacoplar tipos do coordenador).

---

### TD-003: Fragmentação de 5 Modelos de Ordem e Abstrações de Corretora
- **Subsistema**: Execução / Corretagem e Custódia Paper
- **Severidade**: **ALTO**
- **Raio de Impacto**: Camada de execução de ordens, concorrência e reconciliação
- **Causa Raiz**: Implementações paralelas desenvolvidas para atender demandas temporárias (Cedro legada, simulação de OMS in-memory e wrappers de mercado sem consolidação).
- **Evidências no Código**:
  * `backend/app/agents/executor.py` (`ExecutorAgent`): manipula tabelas `trades` e `portfolio`.
  * `backend/app/markets/paper_broker.py` (`PaperBroker`): wrapper de brokerage não utilizado pela API.
  * `trading_bot/broker/cedro.py` (`CedroBroker`): manipula tabela `paper_trades` sem debitar `portfolio`.
  * `trading_bot/broker/cedro_client.py` (`CedroClient`): cliente REST com tokens fictícios mockados.
  * `trading_bot/execution/order_manager.py` (`OrderManagementSystem`): OMS in-memory órfão em produção.
- **Risco Operacional e Financeiro**:
  * Operadores e desenvolvedores podem utilizar acidentalmente conectores que não realizam dedução atômica de saldo no SQLite.
  * Divergência contábil entre a tabela `trades` e a tabela `paper_trades`.
- **Estratégia de Remediação**:
  * Executar o **ADR-003**: ratificar o protocolo canônico `IOrderBroker`, unificar o `ExecutorAgent` como motor de paper trading em SQLite durável e expurgar a tabela `paper_trades` e os módulos Cedro obsoletos.
- **Esforço Estimado**: 12 horas-homem.
- **Dependências**: Nenhuma prévia.

---

### TD-004: Disparidade Contábil de Custos da B3 no Executor de Paper Trading
- **Subsistema**: Execução / Gestão de Risco
- **Severidade**: **ALTO**
- **Raio de Impacto**: Integridade e fidelidade financeira dos resultados de paper trading
- **Causa Raiz**: O cálculo de PnL no `ExecutorAgent` foi implementado como uma fórmula percentual simples de marcação a mercado sem considerar as taxas operacionais da Bolsa de Valores brasileira.
- **Evidências no Código**:
  * `backend/app/agents/executor.py:168`:
    `pnl_pct = ((current_price - entry_price) / entry_price) * 100`
  * Em contrapartida, `trading_bot/data/model_evaluation.py` impõe dedução estrita de **10.0 bps por operação** (emolumentos B3 + liquidação CBLC).
- **Risco Operacional e Financeiro**:
  * O sistema em Paper Trading reporta lucros inflados e perdas atenuadas em comparação com o modelo validado em pesquisa quantitativa.
  * Falsa impressão de viabilidade em estratégias de baixa margem ou alta rotação de carteira.
- **Estratégia de Remediação**:
  * Executar o **ADR-003** (Seção 4.4): incorporar formalmente o desconto de 10.0 bps no cálculo de `pnl_pct` e no crédito de caixa de fechamento no `ExecutorAgent`.
- **Esforço Estimado**: 4 horas-homem.
- **Dependências**: TD-003.

---

### TD-005: Desconexão da Governança de Correlação para Ativos B3
- **Subsistema**: Governança de Risco Pré-Trade
- **Severidade**: **ALTO**
- **Raio de Impacto**: Portão pré-trade de validação de ordens (`RiskManager`)
- **Causa Raiz**: Código herdado de protótipo de criptoativos mantido inadvertidamente no arquivo `risk_manager.py`.
- **Evidências no Código**:
  * `backend/app/agents/risk_manager.py:5-8`:
    `CORRELATED_GROUPS: List[List[str]] = [["BTC-USD", "ETH-USD"]]`
  * `trading_bot/risk/correlation.py`: Apenas extrai matriz de retornos; não calcula correlação.
  * `trading_bot/risk/circuit_breaker.py:171`: Contém `check_correlation` com correlação de Pearson, mas **nunca é chamado pelo `RiskManager`**.
- **Risco Operacional e Financeiro**:
  * A carteira pode acumular 100% de exposição em ativos do mesmo setor econômico (ex.: múltiplas empresas petrolíferas ou múltiplos bancos), alavancando inadvertidamente o risco de cauda e violando o objetivo de diversificação.
- **Estratégia de Remediação**:
  * Executar o **ADR-004**: realocar `check_correlation` para `correlation.py`, conectar ao `RiskManager` com política fail-closed e remover a lista estática de criptoativos.
- **Esforço Estimado**: 6 horas-homem.
- **Dependências**: Nenhuma prévia.

---

### TD-006: Configurações Fantasma e Falta de Schema Pydantic Estrito em `settings.yaml`
- **Subsistema**: Configuração e Governança de Parâmetros
- **Severidade**: **MÉDIO**
- **Raio de Impacto**: Setup operacional, consistência de execução e auditoria
- **Causa Raiz**: Declaração de parâmetros no YAML que foram descontinuados no código ou idealizados sem implementação correspondente.
- **Evidências no Código**:
  * 12 parâmetros órfãos catalogados na Seção 5 do Relatório de Auditoria (`rate_limit.*`, `genetic_optimizer.*`, `redis_url`, `poll_interval_seconds`, etc.).
  * `backend/app/runtime_config.py` e `trading_bot/core/config.py` utilizam leituras tolerantes sem `extra="forbid"`.
- **Risco Operacional e Financeiro**:
  * Erros humanos de digitação no arquivo de configuração são ignorados silenciosamente, operando com parâmetros default inesperados.
- **Estratégia de Remediação**:
  * Executar o **ADR-005**: expurgar chaves órfãs do YAML e adotar schema Pydantic estrito com validações semânticas de limites financeiros.
- **Esforço Estimado**: 4 horas-homem.
- **Dependências**: Nenhuma prévia.

---

### TD-007: Conflito de Concorrência de Banco no `docker-compose.yml`
- **Subsistema**: DevOps / Implantação de Infraestrutura
- **Severidade**: **ALTO**
- **Raio de Impacto**: Ambientes de homologação e produção rodando via Docker
- **Causa Raiz**: O `docker-compose.yml` orquestra dois serviços (`bot` e `api`) que compartilham o mesmo volume SQLite (`./data:/app/data`). O container `bot` dispara um cron rodando o script legado `fase2_paper_trading.py`, enquanto o container `api` roda os workers assíncronos contínuos.
- **Evidências no Código**:
  * `docker-compose.yml:10-25`: Definição dos dois serviços concorrentes.
  * `Dockerfile:28`: Entrypoint ativando cron do script legado.
- **Risco Operacional e Financeiro**:
  * Contenção de escrita e potenciais locks no arquivo SQLite `trading_bot.db`.
  * Dois processos distintos tomando decisões conflitantes de compra e venda sobre a mesma carteira física.
- **Estratégia de Remediação**:
  * Refatorar o `docker-compose.yml` para executar apenas o serviço da API unificada com o `CentralCoordinator` supervisionando as tarefas em background. Desativar o serviço autônomo `bot` ou configurá-lo como réplica de leitura estrita.
- **Esforço Estimado**: 4 horas-homem.
- **Dependências**: TD-002, TD-003.

---

### TD-008: 10 Módulos Satélite Avançados Desconectados da Operação
- **Subsistema**: Pesquisa Quantitativa (`trading_bot/data/quant/`)
- **Severidade**: **BAIXO**
- **Raio de Impacto**: Manutenibilidade e volume de testes
- **Causa Raiz**: Desenvolvimento exploratório de filtros avançados (Kalman, PCA, cointegração de pares, RAG semântico) que foram testados unitariamente mas não integrados ao pipeline de geração de sinais.
- **Evidências no Código**:
  * Módulos em `trading_bot/data/quant/`: `kalman_filter.py`, `pairs_cointegration.py`, `market_pca.py`, `regime_clustering.py`, `dynamic_sizing.py`, etc.
  * Apenas `neural_engine.py` e `regularized_logistic.py` são consumidos por `scripts/evaluate_research_models.py`.
- **Risco Operacional e Financeiro**:
  * Sobrecarga de manutenção de código sem benefício operacional imediato na carteira viva.
- **Estratégia de Remediação**:
  * Manter os módulos sob quarentena formal de pesquisa até que surjam propostas de melhoria de estratégia (EIP - Enhancement Proposals).
- **Esforço Estimado**: 2 horas-homem (documentação).
- **Dependências**: Nenhuma prévia.

---

### TD-009: Monólito de 1.412 Linhas em `backend/app/main.py`
- **Subsistema**: Camada Web / API
- **Severidade**: **MÉDIO**
- **Raio de Impacto**: Manutenibilidade e testabilidade da API
- **Causa Raiz**: Acúmulo progressivo de rotas REST, tarefas assíncronas, regras de autenticação e manipulação de estado em um único arquivo de inicialização.
- **Evidências no Código**:
  * `backend/app/main.py` possui 1.412 linhas e concentra: definição do FastAPI, lifespan, endpoints de autenticação, endpoints de patrimônio, endpoints de trades, supervisores manuais e formatação de payloads.
- **Risco Operacional e Financeiro**:
  * Dificuldade de auditoria e elevado risco de regressões em alterações nas rotas web.
- **Estratégia de Remediação**:
  * Decompor `main.py` em roteadores modulares (`backend/app/routers/`): `portfolio.py`, `trades.py`, `status.py`, `signals.py`, mantendo `main.py` apenas como ponto de composição e injeção do ciclo de vida.
- **Esforço Estimado**: 8 horas-homem.
- **Dependências**: TD-002.

---

### TD-010: Cache de Cotações In-Memory não Compartilhado com Scraping Direto
- **Subsistema**: Ingestão de Dados de Mercado
- **Severidade**: **MÉDIO**
- **Raio de Impacto**: Latência de cotações e resiliência de dados
- **Causa Raiz**: O mecanismo de cache em `backend/app/data/feed.py` é um dicionário Python em memória com TTL de 15 segundos. Se múltiplos workers ou processos forem acionados, cada um mantém seu próprio cache e realiza chamadas redundantes para o Yahoo Finance.
- **Evidências no Código**:
  * `backend/app/data/feed.py:15-30`: `_cache: Dict[str, Tuple[float, float]] = {}`.
- **Risco Operacional e Financeiro**:
  * Risco de bloqueio por rate limiting de APIs públicas de cotação durante pregões de alta volatilidade.
- **Estratégia de Remediação**:
  * Centralizar o cache de preços no SQLite em uma tabela dedicada com TTL ou memória compartilhada (ex.: SQLite em modo `:memory:` com URI compartilhada).
- **Esforço Estimado**: 6 horas-homem.
- **Dependências**: Nenhuma prévia.

---

## 3. Roadmap de Remediação em Fases

A eliminação dos débitos técnicos deve seguir uma sequência estrita para evitar quebras de compatibilidade ou violação das salvaguardas financeiras.

```text
┌────────────────────────────────────────────────────────────────────────┐
│ FASE 1: Saneamento Imediato de Risco e Configuração (P2 - Baixo Risco) │
│ - TD-005: Governança de correlação dinâmica B3 (ADR-004)               │
│ - TD-006: Poda de configurações fantasma e schema estrito (ADR-005)   │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│ FASE 2: Unificação de Supervisão e Modularização API (P1 - Médio Risco)│
│ - TD-002: Iniciar CentralCoordinator no lifespan (ADR-002)             │
│ - TD-009: Decompor monólito main.py em rotas modulares                 │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│ FASE 3: Desacoplamento do Núcleo Quantitativo (P1 - Médio Risco)       │
│ - TD-001: Eliminar imports trading_bot -> backend.app (ADR-001)        │
│ - TD-010: Centralizar cache de cotações                                │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│ FASE 4: Padronização de Execução e Deploy Seguro (P1 - Médio Risco)    │
│ - TD-003: Padronizar IOrderBroker e expurgar paper_trades (ADR-003)    │
│ - TD-004: Aplicar fricção de 10 bps no PnL do ExecutorAgent (ADR-003)  │
│ - TD-007: Eliminar concorrência do cron no docker-compose.yml          │
└────────────────────────────────────────────────────────────────────────┘
```

### Critérios Inegociáveis de Liberação de Cada Fase:
1. Todos os 822+ testes unitários e de integração devem passar com 100% de sucesso.
2. Invariante `real_broker_calls == 0` verificada e auditada via tripwires automatizados.
3. Arquivos reservados P0 mantidos intactos e intocados.
