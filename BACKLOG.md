# Backlog Meridian

Itens conhecidos, ainda não implementados. Marcados por prioridade.

## Alta prioridade

- **`get_risk_metrics()` (`backend/app/data/database.py`) tem um campo
  fabricado e um mal rotulado — achado durante o honest-dashboard Bloco
  3.** `"calmar": sharpe * 0.8` (comentário no próprio código: `#
  Approximated`) não tem relação nenhuma com a fórmula real de Calmar
  Ratio (retorno anualizado / max drawdown) — é um placeholder que imita
  métrica real, exatamente o que a regra nova do CLAUDE.md proíbe.
  `max_drawdown_pct` também é enganoso: hoje é só o pior trade individual
  (`min(losses)`), não o drawdown pico-a-vale real da curva de
  patrimônio — que agora dá pra calcular de verdade a partir de
  `equity_snapshots` (`GET /api/equity_snapshots`, Bloco 3). `sharpe`/
  `sortino`/`var_95_daily` são aproximações honestas mas não-padrão
  (retornos por trade, não série temporal anualizada com taxa livre de
  risco) — value real, só não é a métrica clássica que o nome sugere;
  vale um aviso na UI ou renomear os campos. Decidir: implementar calmar/
  drawdown de verdade a partir da equity curve, ou remover/renomear os
  campos até existir cálculo real.
  Arquivos: `backend/app/data/database.py` (`get_risk_metrics`),
  `frontend/src/EliteCharts.jsx` (`RiskMetricsPanel`).

- **Latência de stop-loss: PHASE 1 (saídas) só reavaliada a cada ciclo completo (10+ min).**
  Enquadramento: isto NÃO é performance — é latência de proteção de capital.
  O worker processa os tickers sequencialmente num único `for`; cada ticker em
  PHASE 2 (entrada) gasta 4–7 s em `await asyncio.sleep(2)` fixos (cadência de
  UI/log). Com 50 tickers, o ciclo passa de 10 min (ver medição no item de
  heartbeat abaixo). Consequência: a PHASE 1 (checagem de stop/target de uma
  posição aberta) de um dado ticker só roda uma vez por ciclo. **Um stop furado
  no minuto 2 só seria percebido no minuto 12.** Num bot que gerencia stop-loss,
  isso é risco direto de capital.

  **Solução proposta (decidir e implementar; pode ser mais urgente que o P3):**
  1. **Separar a cadência da PHASE 1 da PHASE 2.** Saídas (gestão de posições
     abertas) precisam de um laço próprio, rápido (poucos segundos), varrendo só
     os tickers com posição ativa — que são poucos. Entradas (PHASE 2, análise
     LLM de todo o universo) podem seguir num laço mais lento. Assim o stop de
     qualquer posição é reavaliado em segundos, independente do tamanho do
     universo.
  2. **Remover / reduzir drasticamente os `sleep(2)`.** São só espaçamento de
     log/UI; não têm função de trading. Removê-los encolhe o ciclo em ~200–350 s.
     Pode ser feito junto de (1) ou como primeiro passo isolado.
  Observação: FAIL-CLOSED continua valendo — a separação não pode deixar a
  PHASE 1 rodar com feed/preço não confiável.
  Arquivos: `backend/app/main.py` (`_run_one_scan_cycle` — PHASE 1 vs PHASE 2),
  `backend/app/worker_state.py` (cadências separadas, se necessário).

## Risco / Resiliência

- **Heartbeat marcado só no fim do ciclo → falso alarme com worker saudável.**
  O P2 grava o heartbeat (`mark_scan`) apenas quando `_run_one_scan_cycle()`
  termina. Um ciclo real sobre o universo atual (50 tickers) NÃO cabe dentro do
  `HEARTBEAT_TIMEOUT_SECONDS` (300s / 5 min), então `worker_alive` vira `false`
  com o worker saudável — falso alarme recorrente, e alarme que dispara à toa
  vira alarme ignorado.

  **Medição (13/07/2026, 50 tickers):**
  - Loop por ticker: ~4,8 s/ticker medido (16 tickers em ~77 s) → ~4–5 min só o
    laço, e uma execução completa NÃO terminou dentro de um teto de 10 min
    (o yfinance passa a limitar as chamadas e o backoff de retry do feed
    adiciona esperas crescentes — gaps de ~11 s observados no fim do ciclo).
  - Piso determinístico só dos `await asyncio.sleep(2)` fixos da fase de entrada:
    50 tickers × 4 s (todos HOLD) = **200 s**; × 6–7 s (BUY/SELL) = **300–350 s**.
    Ou seja, o piso sozinho já iguala/excede o timeout de 300 s.

  **Decisão tomada (não implementado):** heartbeat **granular** — marcar
  atividade a cada ticker processado dentro do `for`, mantendo SEPARADAS as duas
  noções: "última atividade" (por ticker, base do `worker_alive`) e "último
  ciclo completo". **NÃO aumentar `HEARTBEAT_TIMEOUT_SECONDS`**: detectar um
  worker travado só 15–20 min depois é inaceitável num bot que gerencia
  stop-loss. Um hang no meio do ciclo passa a ser detectado em segundos.
  Provável de ser feito junto do item de alta prioridade acima (a separação de
  cadências torna o heartbeat por atividade natural).
  Arquivos: `backend/app/main.py` (`_run_one_scan_cycle`, `ai_committee_worker`),
  `backend/app/worker_state.py` (`mark_scan`, separar `last_activity_at` de
  `last_full_cycle_at`).

- **P3-B — ResilientLLMClient não é resiliente: não há segundo provedor.**
  `fallback_key` (OpenAI) é armazenado no `__init__` mas nunca usado: o único
  provedor é o Gemini via `_call_gemini`. Se o Gemini cair, `generate_text`
  retorna `None`. **Resolvido pelo P3-A**: o fallback matemático perigoso do
  MarketAnalyst foi removido e a decisão fail-closed foi tomada — falha do LLM
  agora sempre retorna `HOLD`, nunca abre posição por engano. **Ainda em
  aberto (P3-B)**: isso significa que uma queda do Gemini deixa o bot
  efetivamente parado (todo sinal vira HOLD) até o provedor voltar — seguro,
  mas sem resiliência real. Implementar o fallback OpenAI de verdade (ou
  decidir explicitamente que "parar" é aceitável e documentar isso como
  comportamento pretendido, não lacuna).
  Arquivos: `trading_bot/core/llm_client.py`, `backend/app/agents/market_analyst.py`.

- **`llm.failure_policy` aceita `"technical_fallback"` no YAML mas é dead
  code.** `RuntimeConfig` valida e expõe `llm_failure_policy` (`hold` |
  `technical_fallback`), mas nenhum consumidor (`market_analyst.py`,
  `risk_manager.py`, `llm_client.py`) lê esse campo — o comportamento real é
  sempre `HOLD` hardcoded em `market_analyst.py`, independente do valor
  configurado. Não é vulnerabilidade (o hardcode é fail-safe), mas é uma
  opção enganosa: promete um comportamento (`technical_fallback`) que nunca é
  entregue. Ou implementar de verdade (junto do P3-B acima) ou remover a
  opção do config até existir.
  Arquivos: `backend/app/runtime_config.py`, `backend/app/agents/market_analyst.py`.

- **`RuntimeConfig.load()` relendo `config/settings.yaml` do disco a cada
  ticker do laço de entradas (~50x/ciclo), não 1x.** A Etapa 4 adicionou a
  checagem de `autonomous_entries_enabled` dentro do `for ticker in
  tickers_to_watch:`, chamando `RuntimeConfig.load()` (I/O síncrono, sem
  cache, abre e faz parse de dois arquivos YAML) a cada iteração — antes,
  `entradas_liberadas` já era calculado 1x fora do loop e reusado. Não é bug
  funcional (o comportamento continua correto), é I/O síncrono redundante
  bloqueando o event loop compartilhado com o `exit_loop` ~50x por ciclo em
  vez de 1x. Corrigir movendo `RuntimeConfig.load()` para antes do loop, ao
  lado de `entradas_liberadas`, reusando o resultado dentro do loop (mesmo
  padrão já usado para `entradas_liberadas`).
  Arquivos: `backend/app/main.py` (`_run_one_scan_cycle`).

- **Docstring/comentário de `risk_manager.py` ainda citam "10%" fixo.** O
  limite de posição virou parametrizável via `config/settings.yaml`
  (`max_position_fraction`, hardening pós-Etapa 4), mas a docstring da classe
  e um comentário interno ainda dizem "Maximum allocation limit bumped to
  10%" / "Max risk allowed is 10%" — podem confundir quem for alterar o valor
  depois, já que o número real agora vem do config, não do código.
  Arquivos: `backend/app/agents/risk_manager.py` (linhas ~29-30, ~39).

## Higiene de dependências

- **`pytest`/`pytest-asyncio` estão no `requirements.txt` de produção.** São
  ferramentas de teste e não deveriam ir para o ambiente de produção (o deploy
  instala só o `requirements.txt`). O lugar delas é o `requirements-dev.txt`.
  Não movidas no PR de fix do CI (`fix/ci-deps`) para manter aquele fix focado
  em declarar o que faltava. Mover num PR próprio de higiene.
- **Produção não está pinada com `==`.** Após o PR `fix/ci-deps`, só
  `pydantic==2.11.10` está pinado exato no `requirements.txt`; todo o resto usa
  faixas `>=` (`pandas>=2.0`, `yfinance>=0.2.40`, `requests>=2.31`, `pyyaml>=6.0`,
  `google-generativeai>=0.5`, `anthropic>=0.30`, `schedule>=1.2`, `numpy>=1.26`,
  `scipy>=1.13`, `click>=8.1`, `pytest>=8.0`, `pytest-asyncio>=0.23`,
  `fastapi>=0.111`, `uvicorn>=0.30`, `redis>=5.0.0`, `PyMySQL>=1.1.0`,
  `cryptography>=42.0.0`, `SQLAlchemy>=2.0.0`). Faixas permitem drift silencioso
  entre CI/dev/produção — indesejável num sistema financeiro. Pinar tudo com `==`
  (idealmente via lockfile: `pip-compile`/`pip freeze`) num PR próprio.
