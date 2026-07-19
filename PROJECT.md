# Arquitetura do Meridian

## Objetivo

O Meridian é uma plataforma de pesquisa quantitativa e Paper Trading para ativos da B3. A versão atual não envia ordens reais.

## Componentes

- `backend/app/main.py`: composição da API FastAPI e supervisão dos workers.
- `backend/app/runtime_config.py`: configuração operacional validada e fonte única para modo de execução e limites do backend.
- `backend/app/security.py`: autenticação por API key sem credencial padrão.
- `backend/app/agents/`: analista de mercado, gestor de risco e executor simulado.
- `backend/app/data/`: feed, SQLite/WAL, portfólio, trades e snapshots.
- `trading_bot/`: núcleo quantitativo reutilizável para ingestão, sinais, backtests, risco, scheduler e notificações.
- `frontend/`: painel React/Vite conectado por cliente HTTP centralizado.
- `config/settings.yaml`: parâmetros de dados, risco, execução, LLM e infraestrutura.

## Invariantes de segurança

1. Execução é exclusivamente Paper Trading.
2. `execution.mode` vem de `config/settings.yaml`.
3. Nos modos `manual` e `semi_auto`, o worker não abre novas posições automaticamente.
4. Falha de feed, circuit breaker ou resposta LLM inválida bloqueia novas entradas.
5. Saídas permanecem ativas mesmo quando entradas estão bloqueadas.
6. Trade e portfólio são atualizados na mesma transação.
7. Uma posição ativa por ticker é garantida também no banco.
8. A API não possui chave padrão e falha no startup sem `API_KEY`.

## Fluxo operacional

1. Supervisor inicia os loops de entrada e saída.
2. O loop de saída monitora posições, stop e alvo com intervalo curto.
3. O loop de entrada verifica o modo de execução antes da análise.
4. O analista combina dados técnicos com Gemini; qualquer falha retorna `HOLD` por padrão.
5. O gestor de risco usa Kelly fracionado e limites carregados da configuração.
6. O executor registra a ordem no SQLite como simulação local.
7. Heartbeats e reinícios supervisionados são expostos no endpoint `/api/status`.

## Qualidade

O repositório possui testes regulares, testes de concorrência/SQLite e suíte E2E. O CI valida Python 3.11/3.12 e frontend Node.js 22 antes do deploy.

## Evolução recomendada

`backend/app/main.py` ainda concentra composição, workers e rotas. A próxima refatoração arquitetural deve separar `routers/`, `services/` e `workers/` em mudanças pequenas e cobertas por testes, sem alterar o comportamento operacional.
