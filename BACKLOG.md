# Backlog Meridian

Itens conhecidos, ainda não implementados. Ordem não implica prioridade.

## Risco / Resiliência

- **ResilientLLMClient não é resiliente — não há segundo provedor.**
  `fallback_key` (OpenAI) é armazenado no `__init__` mas nunca usado: o único
  provedor é o Gemini via `_call_gemini`. Se o Gemini cair, `generate_text`
  retorna `None`. Hoje isso fica mascarado pelo fallback matemático do
  MarketAnalyst (lógica de trend simples). **Tratar junto do P3**, que remove
  esse fallback matemático — ao removê-lo, a ausência de segundo provedor LLM
  fica exposta e precisa de solução real (implementar o fallback OpenAI ou
  decidir explicitamente por fail-closed quando o LLM não responder).
  Arquivos: `trading_bot/core/llm_client.py`, `backend/app/agents/market_analyst.py`.

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

  **Decisão a tomar (não implementado):**
  1. **Heartbeat granular (preferível):** chamar `mark_scan()` a cada ticker
     processado dentro do `for`, não só no fim do ciclo. O heartbeat avança
     continuamente, um hang no meio do ciclo é detectado rápido e não é preciso
     adivinhar um timeout "seguro". Requer separar "última atividade" (por
     ticker) de "último ciclo completo" se quisermos manter as duas noções.
  2. **Aumentar `HEARTBEAT_TIMEOUT_SECONDS`** para acima do pior caso medido
     (ex.: 15–20 min). Mais simples, porém atrasa a detecção de um worker
     realmente travado e exige re-medir se o universo/latência crescer.
  - Alavanca secundária: os `sleep(2)` fixos são só cadência de UI/log e
    dominam o custo; reduzi-los encolheria o ciclo drasticamente (avaliar à
    parte, pode mudar o número acima).
  Arquivos: `backend/app/main.py` (`_run_one_scan_cycle`, `ai_committee_worker`),
  `backend/app/worker_state.py` (`HEARTBEAT_TIMEOUT_SECONDS`, `mark_scan`).
