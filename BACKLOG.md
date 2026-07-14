# Backlog Meridian

Itens conhecidos, ainda não implementados. Marcados por prioridade.

## Alta prioridade

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

- **ResilientLLMClient não é resiliente — não há segundo provedor.**
  `fallback_key` (OpenAI) é armazenado no `__init__` mas nunca usado: o único
  provedor é o Gemini via `_call_gemini`. Se o Gemini cair, `generate_text`
  retorna `None`. Hoje isso fica mascarado pelo fallback matemático do
  MarketAnalyst (lógica de trend simples). **Tratar junto do P3**, que remove
  esse fallback matemático — ao removê-lo, a ausência de segundo provedor LLM
  fica exposta e precisa de solução real (implementar o fallback OpenAI ou
  decidir explicitamente por fail-closed quando o LLM não responder).
  Arquivos: `trading_bot/core/llm_client.py`, `backend/app/agents/market_analyst.py`.
