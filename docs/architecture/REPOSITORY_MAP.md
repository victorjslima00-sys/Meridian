# Mapa Arquitetural Empírico dos Subsistemas — Repositório Meridian

- **Protocolo Institucional**: `MERIDIAN-ARCH-MAP-20260914-WS-D`
- **Data da Auditoria**: 2026-09-14
- **Branch de Trabalho**: `team/architecture-audit`
- **Autoridade Responsável**: NEXUS CSOO / ANTIGRAVITY / SENTINEL
- **Regime de Auditoria**: Inspeção Empírica de Código Estático e Dinâmico
- **Invariante Primária de Segurança**: `real_broker_calls == 0` (Incondicional)

---

## 1. Visão Geral da Topologia Arquitetural

A plataforma **Meridian** é um sistema institucional de negociação quantitativa para o mercado de ações brasileiro (B3), operando sob arquitetura em camadas orientada a contratos determinísticos e salvaguardas *fail-closed*. 

A base de código é composta por aproximadamente 6.117 linhas de Python divididas entre o núcleo quantitativo reutilizável (`trading_bot/`) e a camada web/operacional (`backend/app/`), suportada por uma suíte de testes automatizados com 822 testes passando (cobertura global de 84.67%).

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            CAMADA DE EXPOSIÇÃO (WEB/API)                         │
│   backend/app/main.py (FastAPI, Rotas REST, Auth, Telemetria)                    │
└──────────────────────────┬─────────────────────────────┬─────────────────────────┘
                           │                             │
┌──────────────────────────▼──────────────────────┐ ┌────▼────────────────────────┐
│      SUB-7: COORDENAÇÃO & SUPERVISÃO            │ │    SUB-8: INTERFACE WEB     │
│   trading_bot/core/coordinator.py               │ │    frontend/src/ (React 18) │
│   backend/app/worker_state.py                   │ │    Tailwind, Lucide, Vite   │
└──────────────┬──────────────────────────┬───────┘ └─────────────────────────────┘
               │                          │
┌──────────────▼─────────────┐ ┌──────────▼────────────────┐
│ SUB-4: SINAIS & ANÁLISE    │ │ SUB-5: RISCO & CIRCUIT    │
│ trading_bot/signals/       │ │ trading_bot/risk/         │
│ backend/app/agents/market* │ │ backend/app/agents/risk*  │
└──────────────┬─────────────┘ └──────────┬────────────────┘
               │                          │
┌──────────────▼──────────────────────────▼────────────────┐
│ SUB-6: EXECUÇÃO, CORRETAGEM & CUSTÓDIA PAPER             │
│ backend/app/agents/executor.py | trading_bot/execution/  │
│ SQLite WAL (tabelas trades, portfolio)                   │
└──────────────┬──────────────────────────┬────────────────┘
               │                          │
┌──────────────▼─────────────┐ ┌──────────▼────────────────┐
│ SUB-1: INGESTÃO & FEEDS    │ │ SUB-2: PROVENIÊNCIA &     │
│ backend/app/data/feed.py   │ │        LAKEHOUSE          │
│ trading_bot/data/cotahist  │ │ valuation_snapshot.py     │
│ trading_bot/data/ingestion │ │ storage_manager.py (SHA)  │
└──────────────┬─────────────┘ └──────────┬────────────────┘
               │                          │
┌──────────────▼──────────────────────────▼────────────────┐
│ SUB-3: PESQUISA QUANTITATIVA & MODELAGEM TEMPORAL        │
│ trading_bot/data/model_evaluation.py                     │
│ trading_bot/backtest/engine.py                           │
└──────────────────────────────────────────────────────────┘
```

---

## 2. Matriz Consolidada dos Subsistemas

| ID | Subsistema | Proprietário Institucional | Entrypoint Primário | Persistência / Mutações | Dependências Externas | Invariante Primária | Cobertura de Testes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **SUB-1** | Ingestão & Feeds de Mercado | ANTIGRAVITY | `backend/app/data/feed.py` | Cache in-memory, SQLite `ohlcv` | `yfinance`, B3 COTAHIST, Bacen API | Fail-closed em preço inválido (0.0/None); sem forward-fill sem evento. | 89% (28 testes) |
| **SUB-2** | Proveniência & Lakehouse | CEO ASTRA | `trading_bot/data/valuation_snapshot.py` | Arquivos JSON, manifestos SHA-256, SQLite `valuation_snapshots` | FS local (`fsync`, O_EXCL) | `is_valid==1` e SHA-256 válido obrigatórios para publicar equity. | 94% (45 testes) |
| **SUB-3** | Pesquisa & Modelos Temporais | NEXUS CSOO | `trading_bot/data/model_evaluation.py` | JSONs em `reports/model_evaluations/` | NumPy, Pandas, Scikit-learn | $Train_{end} < Val_{start} < Test_{start}$; `is_approved_for_signals: False`; 10 bps taxa B3. | 86% (38 testes) |
| **SUB-4** | Sinais & Análise Técnica | ANTIGRAVITY | `trading_bot/signals/engine.py` | Nenhuma (funções puras sobre DataFrames) | Gemini API (opcional), Yahoo Finance | Falha em dados técnicos ou IA resulta estritamente em `HOLD`; $SL < P < TP$. | 91% (34 testes) |
| **SUB-5** | Governança de Risco & Circuit Breaker | SENTINEL | `trading_bot/risk/circuit_breaker.py` | Consulta `equity_snapshots`, `portfolio` | SQLite `trading_bot.db` | Perda diária máx 3%, DD total 8%, Kelly fracionado (0.25), veto em falta de dados. | 95% (42 testes) |
| **SUB-6** | Execução & Corretagem Paper | SENTINEL / ANTIGRAVITY | `backend/app/agents/executor.py` | SQLite `trades`, `portfolio`; journal `.jsonl` | SQLite WAL, `os.fsync` | `real_broker_calls == 0`; 1 posição por ticker via índice único parcial. | 88% (52 testes) |
| **SUB-7** | Coordenação & Supervisão | NEXUS CSOO | `trading_bot/core/coordinator.py` | Memória (`WorkerEvent`), `LoopSupervisionState` | asyncio, Telegram API (opcional) | Backoff exp ($2^{rc-1} \le 30\,\text{s}$); máx 5 retries; parada aciona `exit_gate_sticky_block`. | 92% (39 testes) |
| **SUB-8** | API Web & Exposição | Victor (Fundador) | `backend/app/main.py` | Transações de trades via endpoints | FastAPI, Starlette, React 18 | Autenticação obrigatória; zero credenciais padrão; sem snapshot = status `unavailable`. | 82% (48 testes) |
| **SUB-9** | Infraestrutura & DevOps | Victor (Fundador) | `Dockerfile`, `infra/aws/compute.tf` | Containers Docker, instâncias EC2 | Docker, AWS EC2, GitHub Actions | Zero credenciais no git (`test_seguranca_segredos.py`); CI estrito antes do deploy. | 100% (24 testes) |

---

## 3. Detalhamento Empírico por Subsistema

### 3.1. SUB-1: Ingestão & Feeds de Mercado
- **Proprietário Institucional**: ANTIGRAVITY (Engenharia de Software)
- **Papel Arquitetural**: Coleta, padronização, reconciliação e cache de séries históricas de preços e cotações intraday de ativos negociados na B3.
- **Componentes e Arquivos**:
  * `backend/app/data/feed.py`: Cache em memória de cotações com TTL de 15 segundos e chamada para Yahoo Finance.
  * `trading_bot/data/ingestion.py`: Pipeline de extração e validação de candles diários.
  * `trading_bot/data/cotahist_loader.py`: Leitor determinístico dos arquivos de dados históricos oficiais da B3 (COTAHIST_A*.TXT) com parsing posicional fixo e validação de trailer de integridade.
  * `trading_bot/data/data_reconciliation.py`: Motor de reconciliação centavo-a-centavo entre feeds com cálculo de resíduos e detecção de `MISSING_DATA`.
- **Entrypoints Primários**:
  * `backend.app.data.feed.get_current_price(ticker: str) -> Optional[float]`
  * `trading_bot.data.ingestion.get_market_data(ticker, start_date, end_date) -> pd.DataFrame`
  * `trading_bot.data.cotahist_loader.load_cotahist_daily(filepath) -> pd.DataFrame`
- **Mutações de Estado e Persistência**:
  * Atualiza o dicionário em memória `feed._cache[ticker] = (price, timestamp)`.
  * Persiste séries temporais normalizadas na tabela SQLite `ohlcv`.
- **Dependências Externas**: `yfinance`, `requests`, APIs públicas do Banco Central do Brasil (SGS).
- **Invariantes e Salvaguardas**:
  * Cotações nulas ou negativas retornam imediatamente `None` ou `0.0`.
  * Reconciliação sem correspondência corporativa documentada gera status `UNEXPLAINED_MISMATCH`.
  * Proibição estrita de forward-fill ou interpolação sintética de preços ausentes.
- **Testes e Cobertura**: `tests/test_ingestion.py`, `tests/test_cotahist.py`, `tests/test_data_reconciliation.py` (89% de cobertura).
- **Dívida Técnica**: O cache de 15s em `feed.py` é in-memory e não compartilhado entre múltiplos processos; ausência de circuit breaker para rate limit do Yahoo Finance.

---

### 3.2. SUB-2: Proveniência Criptográfica & Lakehouse
- **Proprietário Institucional**: CEO ASTRA (Governança e Confiabilidade de Ativos)
- **Papel Arquitetural**: Registro imutável, auditável e criptograficamente verificado de todas as avaliações patrimoniais e séries históricas de dados brutos.
- **Componentes e Arquivos**:
  * `trading_bot/data/valuation_snapshot.py`: Ponto focal de snapshot patrimonial com cálculo atômico de caixa, posições e marcação a mercado.
  * `trading_bot/data/metric_provenance.py`: Agente validador de proveniência de métricas contra registros homologados em `config/metric_approvals.json`.
  * `trading_bot/data/lakehouse/storage_manager.py`: Armazenamento de dados em formato Lakehouse com manifestos SHA-256 e escrita atômica com `O_EXCL`.
- **Entrypoints Primários**:
  * `trading_bot.data.valuation_snapshot.create_valuation_snapshot(db_path) -> ValuationSnapshot`
  * `trading_bot.data.valuation_snapshot.get_latest_valuation_snapshot(db_path) -> Optional[ValuationSnapshot]`
  * `trading_bot.data.metric_provenance.MetricProvenanceAgent.verify_metric(metric_id, value) -> ProvenanceReport`
- **Mutações de Estado e Persistência**:
  * Gravação de registros append-only na tabela SQLite `valuation_snapshots`.
  * Escrita de arquivos `.json` e manifestos de hash `.sha256` em `data/snapshots/` e `data/lakehouse/raw/`.
- **Dependências Externas**: Biblioteca nativa `hashlib` (SHA-256), `sqlite3`, `os` (`fsync`).
- **Invariantes e Salvaguardas**:
  * `is_valid == 1` e correspondência perfeita de hash SHA-256 são pré-requisitos absolutos para exibição de métricas na API ou no painel.
  * Se o snapshot estiver ausente ou corrompido, a API retorna `value: null` e `verification_status: "unavailable"`.
  * Zero injeção de constantes sintéticas de patrimônio (ex.: banimento literal de R$ 1.000.000,00 artificial).
- **Testes e Cobertura**: `tests/test_valuation_snapshot.py`, `tests/test_metric_provenance.py`, `tests/test_lakehouse_raw_persistence.py` (94% de cobertura).
- **Dívida Técnica**: O arquivo `config/metric_approvals.json` é mantido manualmente; ausência de automação de rotação de chaves.

---

### 3.3. SUB-3: Pesquisa Quantitativa & Modelagem Temporal
- **Proprietário Institucional**: NEXUS CSOO (Operações e Estratégia)
- **Papel Arquitetural**: Pesquisa, treinamento, validação walk-forward e avaliação de modelos estatísticos e preditivos de retorno financeiro.
- **Componentes e Arquivos**:
  * `trading_bot/data/model_evaluation.py`: Framework de validação walk-forward e cálculo de métricas de Sharpe, Sortino, Calmar e Max Drawdown com dedução de taxas.
  * `trading_bot/backtest/engine.py`: Motor de backtesting orientado a eventos com suporte a múltiplos ativos e custos de transação.
  * `trading_bot/data/quant/`: Coleção de 12 módulos quantitativos especializados (`kalman_filter.py`, `pairs_cointegration.py`, `neural_engine.py`, etc.).
  * `scripts/evaluate_research_models.py`: Pipeline CLI de calibração e avaliação de modelos de pesquisa.
- **Entrypoints Primários**:
  * `trading_bot.data.model_evaluation.evaluate_walk_forward(strategy, data, splits) -> EvaluationReport`
  * `trading_bot.backtest.engine.BacktestEngine.run() -> BacktestResult`
- **Mutações de Estado e Persistência**:
  * Emissão de relatórios em JSON estruturado sob `reports/model_evaluations/`.
- **Dependências Externas**: `numpy`, `pandas`, `scipy`, `scikit-learn` (opcional).
- **Invariantes e Salvaguardas**:
  * Contrato Temporal Estrito: $Train_{end} < Val_{start} < Test_{start}$; qualquer vazamento de lookahead lança `ValueError("temporal_leakage_detected")`.
  * O campo `is_approved_for_signals` é estritamente fixado como `False` durante pesquisa até que ocorra homologação formal da governança.
  * Dedução inegociável de 10.0 bps por giro (taxas de negociação e liquidação B3).
- **Testes e Cobertura**: `tests/test_temporal_contract.py`, `tests/test_model_evaluation.py`, `tests/test_engine.py` (86% de cobertura).
- **Dívida Técnica**: 10 dos 12 módulos em `trading_bot/data/quant/` não possuem ligação com o pipeline de produção; scripts de grid search alteram YAMLs por regex.

---

### 3.4. SUB-4: Motor de Sinais & Análise Técnica
- **Proprietário Institucional**: ANTIGRAVITY (Engenharia de Software)
- **Papel Arquitetural**: Geração de sinais técnicos determinísticos (Canais de Donchian, ATR) e triagem qualitativa complementar via Comitê de LLM.
- **Componentes e Arquivos**:
  * `trading_bot/signals/engine.py`: Funções matemáticas puras para extração de rompimento Donchian e cálculo de bandas de ATR.
  * `backend/app/agents/market_analyst.py`: Agente de validação semântica com suporte a LLM (`ResilientLLMClient`).
  * `trading_bot/signals/llm_client.py`: Conector para a API do Google Gemini com política de fallback.
- **Entrypoints Primários**:
  * `trading_bot.signals.engine.compute_signal(df, donchian_entry, donchian_exit, stop_atr_mult, target_atr_mult) -> SignalResult`
  * `backend.app.agents.market_analyst.MarketAnalystAgent.analyze_ticker(ticker) -> AnalystRecommendation`
- **Mutações de Estado e Persistência**:
  * Nenhuma (operações sem efeitos colaterais sobre DataFrames de mercado).
- **Dependências Externas**: `google.generativeai` (opcional/mockável), `pandas`.
- **Invariantes e Salvaguardas**:
  * Qualquer inconsistência ou falha de comunicação da IA gera estritamente a recomendação neutra `HOLD` (*fail-closed*).
  * Validação semântica de preços obrigatória: $\text{Stop Loss} < \text{Preço} < \text{Take Profit}$.
- **Testes e Cobertura**: `tests/test_signals.py`, `tests/test_analyst_schema.py`, `tests/test_backend_agents.py` (91% de cobertura).
- **Dívida Técnica**: Parâmetros de Donchian encontram-se espalhados entre `settings.yaml` e defaults em código; LLM desativado por padrão sem monitoramento de cota.

---

### 3.5. SUB-5: Governança de Risco & Circuit Breakers
- **Proprietário Institucional**: SENTINEL (Gestão de Risco Institucional)
- **Papel Arquitetural**: Guarda inviolável contra perdas financeiras descontroladas, limitando tamanho de posições, drawdown diário e correlação setorial.
- **Componentes e Arquivos**:
  * `trading_bot/risk/circuit_breaker.py`: Avaliação de gatilhos de parada de emergência baseados no histórico de equity e limites configurados.
  * `trading_bot/risk/position_sizing.py`: Dimensionamento prudencial de lotes via critério de Kelly fracionado (0.25) com teto percentual por posição.
  * `trading_bot/risk/correlation.py`: Construção de matriz de retornos e cálculo de correlação de Pearson.
  * `backend/app/agents/risk_manager.py`: Portão pré-trade de validação de ordens.
- **Entrypoints Primários**:
  * `trading_bot.risk.circuit_breaker.CircuitBreaker.can_trade() -> Tuple[bool, str]`
  * `trading_bot.risk.position_sizing.calculate_position_size(equity, price, stop_loss, ...) -> int`
  * `backend.app.agents.risk_manager.RiskManager.evaluate_trade(...) -> RiskDecision`
- **Mutações de Estado e Persistência**:
  * Consulta as tabelas `equity_snapshots`, `trades` e `portfolio` no SQLite.
- **Dependências Externas**: SQLite3 nativo, `numpy`.
- **Invariantes e Salvaguardas**:
  * Perda diária máxima: 3.0%; Drawdown acumulado inception: 8.0%; Drawdown 30 dias: 6.0%.
  * Fator de Kelly: 0.25; Tamanho máximo por posição: 20% do patrimônio líquido.
  * Ausência de dados de patrimônio gera bloqueio preventivo imediato (`can_trade == False`).
- **Testes e Cobertura**: `tests/test_circuit_breaker_can_trade.py`, `tests/test_risk.py`, `tests/test_correlation.py` (95% de cobertura).
- **Dívida Técnica**: `RiskManager` checa grupo hardcoded `["BTC-USD", "ETH-USD"]` (ADR-004); cálculo de correlação alocado indevidamente em `circuit_breaker.py`.

---

### 3.6. SUB-6: Execução, Corretagem & Custódia Paper
- **Proprietário Institucional**: SENTINEL / ANTIGRAVITY
- **Papel Arquitetural**: Roteamento, registro, persistência e acompanhamento transacional de ordens simuladas (paper trading) sobre o mercado B3.
- **Componentes e Arquivos**:
  * `backend/app/agents/executor.py`: Engine canônica de execução com bloqueio transacional SQLite `IMMEDIATE`.
  * `trading_bot/execution/paper_session.py`: Executor de sessões auditadas com diário em `.jsonl`.
  * `backend/app/markets/paper_broker.py`: Fachada que encapsula `ExecutorAgent`.
  * `trading_bot/broker/cedro.py`: Conector legado para a corretora Cedro.
  * `trading_bot/execution/order_manager.py`: OMS em memória com máquinas de estado.
- **Entrypoints Primários**:
  * `backend.app.agents.executor.ExecutorAgent.execute_order(...) -> Dict[str, Any]`
  * `backend.app.agents.executor.ExecutorAgent.close_position(...) -> Dict[str, Any]`
- **Mutações de Estado e Persistência**:
  * Mutações transacionais atômicas nas tabelas `trades` e `portfolio` do SQLite em modo WAL.
  * Diário append-only em `data/paper_session.jsonl` com flush em disco (`os.fsync`).
- **Dependências Externas**: SQLite3 (modo WAL, `busy_timeout = 10000`).
- **Invariantes e Salvaguardas**:
  * Invariante Absoluta: `real_broker_calls == 0`.
  * Concorrência: Apenas 1 posição aberta por ticker (garantido por índice parcial `idx_trades_one_active_per_ticker`).
  * Débito atômico de caixa: Saldo disponível nunca pode ficar negativo.
- **Testes e Cobertura**: `tests/test_executor_concurrency.py`, `tests/test_paper_session.py`, `tests/test_market_abstraction.py` (88% de cobertura).
- **Dívida Técnica**: Coexistência de 5 abstrações de broker/ordens (ADR-003); PnL em paper execution não deduz emolumentos B3 de 10 bps.

---

### 3.7. SUB-7: Coordenação, Supervisão & Ciclo de Vida Assíncrono
- **Proprietário Institucional**: NEXUS CSOO (Operações e Resiliência)
- **Papel Arquitetural**: Orquestração de tarefas em segundo plano, monitoramento de saúde de processos, contenção de falhas e políticas de retry.
- **Componentes e Arquivos**:
  * `trading_bot/core/coordinator.py`: Motor institucional `CentralCoordinator` com registro de workers e eventos estruturados.
  * `backend/app/worker_state.py`: Singleton em memória de telemetria dos laços de execução.
  * `scripts/run_coordinator.py`: Daemon autônomo para execução sem servidor web.
  * `trading_bot/infra/health_monitor.py`: Monitor nativo Win32 de memória física e disco.
- **Entrypoints Primários**:
  * `trading_bot.core.coordinator.CentralCoordinator.register_worker(...)`
  * `trading_bot.core.coordinator.CentralCoordinator.start()`
  * `trading_bot.core.coordinator.CentralCoordinator.stop()`
- **Mutações de Estado e Persistência**:
  * Lista circular de eventos em memória `self.events: List[WorkerEvent]`.
  * Estados atômicos em `backend.app.worker_state.state`.
- **Dependências Externas**: `asyncio`, `ctypes.windll.kernel32` (Windows), `shutil`.
- **Invariantes e Salvaguardas**:
  * Backoff exponencial: Atraso de reinicialização obedece a $2^{\text{retry}-1} \le 30\,\text{s}$.
  * Limite de reinicializações: Máximo de 5 tentativas consecutivas. Ao esgotar, ativa `exit_gate_sticky_block = True`.
- **Testes e Cobertura**: `tests/test_coordinator.py`, `tests/test_worker_supervision.py`, `tests/test_exit_loop.py` (92% de cobertura).
- **Dívida Técnica**: FastAPI `lifespan` instancia `CentralCoordinator` mas roda supervisores manuais legados (ADR-002).

---

### 3.8. SUB-8: Camada de API Web & Painel Operacional
- **Proprietário Institucional**: Victor (Fundador)
- **Papel Arquitetural**: Exposição das interfaces HTTP REST autenticadas e painel reativo em React para visualização e operação manual.
- **Componentes e Arquivos**:
  * `backend/app/main.py`: Aplicação FastAPI (1.412 linhas) com rotas de patrimônio, trades, sinais, controle e segurança.
  * `backend/app/security.py`: Validação de tokens de API, hashing e rejeição de senhas fracas.
  * `frontend/src/`: Aplicação SPA desenvolvida em React 18, Vite e Tailwind CSS.
- **Entrypoints Primários**:
  * `GET /api/status`, `GET /api/portfolio/equity`, `GET /api/positions`
  * `POST /api/trades/execute`, `POST /api/trades/close`
- **Mutações de Estado e Persistência**:
  * Dispara operações sobre a camada de execução e lê snapshots do SQLite.
- **Dependências Externas**: `fastapi`, `starlette`, `uvicorn`, `pydantic`.
- **Invariantes e Salvaguardas**:
  * Todas as rotas de mutação exigem cabeçalho de autenticação válido (`X-API-Key`).
  * A aplicação falha no boot se chaves padrão (`admin123`, `dev-secret`) estiverem presentes.
  * Valores sem snapshot correspondente são exibidos como `null` / indisponível (zero fabricação de dados).
- **Testes e Cobertura**: `tests/test_positions_route.py`, `tests/test_candle_integrity_api.py`, `frontend/honesty.test.mjs` (82% de cobertura).
- **Dívida Técnica**: `main.py` é um arquivo monolítico de 1.412 linhas acumulando responsabilidades de roteamento, controle de concorrência e supervisão.

---

### 3.9. SUB-9: Infraestrutura, Implantação & Topologia DevOps
- **Proprietário Institucional**: Victor (Fundador)
- **Papel Arquitetural**: Empacotamento em containers Docker, orquestração de serviços locais e automação de entrega contínua (CI/CD).
- **Componentes e Arquivos**:
  * `Dockerfile`: Definição da imagem base Debian/Python com cron embutido.
  * `docker-compose.yml`: Orquestração dos serviços `api` e `bot`.
  * `.github/workflows/deploy.yml`: Workflow do GitHub Actions com verificação de SHA e segredos.
  * `tests/test_deploy_governance.py` e `tests/test_seguranca_segredos.py`: Testes de governança estrita.
- **Entrypoints Primários**:
  * `docker compose up -d`
  * `git push origin main` (disparo de governança CI)
- **Mutações de Estado e Persistência**:
  * Instâncias de contêineres e montagem de volumes `./data:/app/data`.
- **Dependências Externas**: Docker Engine, AWS EC2, GitHub Actions.
- **Invariantes e Salvaguardas**:
  * Zero credenciais ou chaves SSH versionadas no repositório (`test_seguranca_segredos.py`).
  * Workflow de deploy só executa em branches autorizadas mediante aprovação explícita e validação prévia de 8 segredos obrigatórios.
- **Testes e Cobertura**: `tests/test_deploy_governance.py`, `tests/test_seguranca_segredos.py` (100% de cobertura, 24 testes passando).
- **Dívida Técnica**: O `docker-compose.yml` monta o mesmo volume para o container `bot` (que roda cron com script legado) e para o container `api` (que roda seus próprios workers), causando concorrência sobre o SQLite.
