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
- No frontend, tudo que parece dado É dado vindo da API, ou não existe.
  Nenhum placeholder que imite métrica real.

## Padrões de qualidade e revisão

### Backend / risco

- Uma fonte de verdade: toda função que outros pontos do sistema também
  precisam (equity, validação de decisão) é escrita UMA vez e reusada, nunca
  reimplementada em paralelo.
- Fail-closed por padrão: dado não confiável, resposta malformada ou
  inválida = não age, loga, alerta — nunca "ação segura" inventada.
- TDD com RED provado: todo fix mostra o teste falhando ANTES da correção,
  não só o GREEN depois. Verificação por mutação nos casos que guardam
  invariante de segurança/autorização.
- Testes de concorrência usam sincronização real (Barrier/Event) para forçar
  sobreposição, nunca dependem de timing por acaso.
- Nunca usar número/limite inventado quando já existe um equivalente
  configurado no sistema — derivar dali, não duplicar.
- Endpoints que expõem "está configurado?" (chaves, credenciais) retornam só
  booleano — auditar todo branch de erro/exceção para garantir que o valor
  em si nunca vaza, nem parcial, nem embutido em mensagem.

### Frontend

- "Tudo que parece dado É dado vindo da API, ou não existe." Nenhum
  placeholder, mock ou número fixo que imite métrica real — vale tanto para
  dado obviamente fake quanto para fórmula com bug que PARECE real (o caso
  mais perigoso, porque passa despercebido).
- Cada fato aparece em UM lugar só na tela.
- Todo card com dado ao vivo tem polling real E indicador de frescor visível
  (timestamp da última atualização) — nunca "atualizado" silenciosamente
  mentiroso.
- Reconciliação matemática entre campos relacionados é verificada com DADOS
  REAIS do backend rodando, não com a leitura do código.
- Conexões ao vivo (WebSocket etc.) precisam de teste AO VIVO — matar e
  reiniciar o serviço de verdade, observar o indicador cair e reconectar
  sozinho — não só revisão de código. Bug de reconexão do PR #13 só foi
  achado assim.
- Zero cálculo de risco ou lógica de negócio no navegador.

### Processo

- Inventário periódico do frontend/superfícies novas — uma limpeza de
  honestidade anterior NÃO garante que uma aba/componente adicionado depois
  segue as mesmas regras. Rodar o checklist acima a cada PR que toca UI.
- Mudança de risco financeiro e mudança de UI nunca no mesmo PR/branch —
  permite revisar e reverter cada um independentemente.
- Antes de criar qualquer branch nova ou revisar/mergear qualquer PR,
  confirme `git log origin/main -1` bate com o que você espera — não confie
  no rótulo "MERGED" do GitHub sem checar CONTRA QUAL branch. Este projeto já
  teve três incidentes desta classe (PR #4, #11, #12), sempre pelo mesmo
  motivo.
