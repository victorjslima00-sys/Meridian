# Backlog Meridian

Itens conhecidos, ainda não implementados. Marcados por prioridade.

## Multi-mercado (encaixe pronto na Fase 1, Commit 1)

- **O que falta para plugar um MERCADO NOVO (ex.: cripto).** A camada
  `backend/app/markets/` já define os protocolos `Market` e `Broker` e traz
  `B3Market` + `PaperBroker`. Adicionar cripto = criar uma implementação de
  `Market` e registrá-la em `markets/__init__.py::get_market`. O que essa
  implementação precisa resolver, que a B3 resolve de um jeito e cripto de
  outro:
  1. **Feed próprio** — a B3 usa yfinance com sufixo `.SA`; cripto usa par
     (BTC-USD) e provavelmente outra fonte (exchange/API), com outra
     granularidade e outro rate limit.
  2. **Calendário 24/7** — `is_open()` na B3 é dia útil + 10:00-17:30; em
     cripto é sempre aberto, e o conceito de "dia de pregão" (usado no
     snapshot diário de equity) precisa de uma convenção explícita (UTC?
     fuso do usuário?).
  3. **Corretora** — `PaperBroker` serve para simular qualquer mercado, mas
     uma corretora real de cripto tem taxa, precisão decimal e mínimo de
     ordem próprios; entra como outra implementação de `Broker`.
  4. **Sem lote/fracionário** — cripto não tem lote padrão nem mercado
     fracionário separado, o que remove a fragmentação de custo que a B3 tem
     (ver item de custo de fracionário abaixo).
  5. **Feriados** — `B3Market.is_open()` NÃO considera feriados da B3 (exigiria
     calendário externo). Um mercado novo precisa decidir o equivalente.
  - Nota: `is_open()` existe mas **não está ligado ao laço de trading** — ligá-la
    mudaria comportamento (hoje o bot opera fora do pregão). É uma decisão
    explícita pendente, não um esquecimento.

## Alta prioridade

- **ROI Global removido do dashboard (Track B, 2026-07-21) — precisa de
  fonte de verdade de capital inicial antes de voltar.** O card calculava
  `((patrimonio_total - 100) / 100) * 100` no frontend (`App.jsx`), com
  `100` fixo no código, sem nenhum registro real de capital inicial
  (não existe `capital_inicial` em `settings.yaml` nem coluna equivalente
  no banco). Rotulado "Retorno Histórico (Real)", o que passava confiança
  indevida a um número sem base. Mais grave: a partir do momento em que o
  CapitalVault (`POST /api/portfolio/depositar`/`retirar`) for usado, esse
  cálculo passaria a misturar **movimentação de capital** com **resultado
  de trading** — um depósito de R$500 apareceria como se fosse lucro de
  500%. Achado durante o diagnóstico do Track B (dashboard-v2), tratado
  como prioridade 1 pelo usuário: "número real com fórmula quebrada,
  rotulado 'Real', que vira mentira ativa assim que o CapitalVault for
  usado".
  **Antes do ROI poder voltar à UI, é preciso um trabalho de backend com o
  mesmo rigor de tudo que mexe em capital**: uma fonte de verdade dedicada
  para capital inicial — coluna própria (ex.: `capital_inicial` em
  `portfolio`, setada uma vez no primeiro depósito real) ou o primeiro
  `equity_snapshot` gravado, **isolada** de depósitos/retiradas
  subsequentes do cofre (senão o mesmo problema de hoje se repete: uma
  movimentação de capital contaminando o cálculo de retorno). Com essa
  fonte definida, o ROI passa a ser `(equity_atual - capital_inicial) /
  capital_inicial`, sem tocar em `patrimonio_reservado` movimentado pelo
  cofre.
  Arquivos: `backend/app/data/database.py` (schema `portfolio`,
  `compute_current_equity`), `backend/app/main.py` (`/api/portfolio`,
  `/api/positions`), `frontend/src/App.jsx` (card removido, ver commit
  do Track B).

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

- **P3-B — Resolvido (2026-07-20): `ResilientLLMClient` agora tem cadeia de
  fallback multi-provedor de verdade.** Motivado por um caso real: o tier
  gratuito do Gemini (`gemini-3.1-flash-lite`) permite só 15 req/min —
  varrer os ~50 tickers do universo em sequência rápida estoura isso em
  segundos (429). Implementado: `gemini -> groq -> cerebras -> github_models
  -> openai`, cada provedor só entra na cadeia se sua chave estiver
  configurada (`GROQ_API_KEY`, `CEREBRAS_API_KEY`, `GITHUB_MODELS_TOKEN` —
  ver `.env.example`); em falha, tenta o próximo; só retorna `None`
  (→ `HOLD` fail-closed, decisão do P3-A) se todos os configurados falharem.
  Groq/Cerebras/OpenAI/GitHub Models usam um único cliente compartilhado via
  SDK `openai` (todos compatíveis com a API da OpenAI, só muda
  `base_url`/`model`). Também adicionado `LLM_CALL_SPACING_SECONDS = 4.5`
  em `main.py` entre chamadas consecutivas do laço de entradas, pra não
  estourar o limite por-minuto de nenhum provedor configurado.
  **Ainda pendente**: só o Gemini está com chave configurada até o usuário
  criar as contas gratuitas dos demais (Groq/Cerebras não exigem cartão;
  GitHub Models usa a conta GitHub já existente) e colar as chaves no
  `.env`. Sem isso, o comportamento é idêntico a antes (só Gemini, fail-closed
  em HOLD se ele falhar).
  Arquivos: `trading_bot/core/llm_client.py`, `backend/app/main.py`,
  `.env.example`, `tests/test_llm_client.py`.
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
