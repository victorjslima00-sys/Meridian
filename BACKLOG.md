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
