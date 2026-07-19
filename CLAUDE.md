# Regras do projeto Meridian

- Este é um bot de trading B3 em PAPER TRADING. Nunca implementar envio real de ordens sem instrução explícita do usuário.
- FAIL-CLOSED: se filtro de risco, circuit breaker ou feed não tiver dado confiável, BLOQUEAR novas entradas (gerenciar saídas é permitido).
- Toda resposta de LLM e entrada externa validada com Pydantic e invariantes semânticas (em BUY: stop_loss < preço < target_price).
- Uma fonte de verdade: execution.mode vem só de config/settings.yaml.
- Sem segredos hardcoded e sem defaults inseguros de API key.
- Escritas em portfolio/trades numa única transação.
- Loops autônomos nunca morrem em silêncio (try/except + alerta Telegram + heartbeat).
- Backtest sem look-ahead (sinais só com ts < current_date).
- Bugfix = primeiro teste que reproduz o bug e falha, depois correção, depois suíte inteira verde: `pytest tests/ --ignore=tests/e2e` (pythonpath vem do `pytest.ini`, não precisa exportar `PYTHONPATH` — funciona igual em bash/PowerShell/macOS).
- CI (Ubuntu) é o juiz final para testes de concorrência/SQLite: locking do SQLite difere entre Windows e Linux, então verde local não garante verde no CI (e vice-versa). Nunca declarar uma correção de concorrência pronta sem confirmar o CI.
- Não commitar data/*.db, .env, *.pem. Não tocar em .agents/.
- Agentes em segundo plano (Workflow/subagents) só com autorização explícita
  do usuário — vale também para revisões de código, não só para
  implementação.
