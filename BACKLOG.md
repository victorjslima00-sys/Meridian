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
