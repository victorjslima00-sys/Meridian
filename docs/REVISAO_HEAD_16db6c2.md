# Revisão das alterações até 16db6c2

Referência local inspecionada: `16db6c2`, árvore inicialmente limpa. O histórico agora contém consolidação do projeto e commits de governança Nexus. Esta revisão não fez commit, push, deploy ou ativação de serviços.

## Feedback

Implementações novas verificadas: snapshot de avaliação, integração à API, runner paper e journal, coordenação de processos e governança Nexus. Não são equivalentes a homologação operacional. Ambos os registros de aprovação permanecem vazios.

O dossiê recebido afirma fechamento dos impedimentos, mas o código ainda contradiz essa conclusão:

1. `scripts/run_paper_session.py` continha sinais PETR4/VALE3 com preços, alvos, stops e confiança literais, passados diretamente ao runner. O CLI não demonstrava sinais calculados sobre dados aprovados e permitia banco padrão. Foi delegada contenção antes de executar o runner.
2. `trading_bot/data/valuation_snapshot.py` recebia preço escalar e preenchia `quote_observed_at=now` e `quote_source=market_feed`. O contrato não comprova origem nem horário da cotação. Foi delegada rejeição explícita desses preços sem evidência.
3. A leitura/persistência dos snapshots e sua ligação com o arquivo aprovado precisam de revisão adicional: declaração de imutabilidade no docstring não basta. Snapshot antigo também precisa de política explícita de atualização.
4. APIs de posições e patrimônio precisam publicar o mesmo estado de avaliação, sem misturar snapshot anterior com registros atuais.
5. O dossiê referencia `backend/app/agents/valuation_snapshot.py`, inexistente no checkout; a implementação está em `trading_bot/data/valuation_snapshot.py`. Isso reforça a necessidade de verificar cada entrega no código.

## Delegação executada

| Agente | Tarefa | Definição de pronto |
|---|---|---|
| audit_paper_current | Auditar runner/journal e conter CLI com sinais fixos | Original preservado; teste falha antes da correção; CLI não executa exemplos como sessão operacional; pendências de retomada documentadas |
| audit_valuation_current | Auditar snapshot/API e corrigir proveniência de cotação ausente | Preço sem fonte/data não produz avaliação válida; nenhum horário de mercado inventado; testes atualizados para o contrato |
| Coordenação | Rever código/testes e atualizar mapa de execução | Relatar limites e resultados efetivamente observados; nenhum aumento de maturidade por contagem de testes |

## Próxima entrega de integração

Responsável proposto: Integração, com revisão independente de Dados. Conectar um provedor de cotação que devolva preço, unidade, fonte, timestamp observado, horário de coleta e referência do bruto preservado. Produzir snapshot exclusivo, ligar leitura de arquivo/banco ao mesmo hash e publicar carteira/posições desse snapshot. Definir validade e renovação sem tratar consulta HTTP como nova observação. Pronto: cenário válido publicável, fonte ausente bloqueada, adulteração detectada e atualização consistente demonstrada.

Depois: conectar sinais calculados sobre dataset aprovado ao ciclo paper e testar interrupção/reinício sem duplicação. Não aprovar dados para destravar uma demonstração.

**Ticket de Execução/Risco (P0):** a biblioteca PaperSessionRunner entrega dict diretamente ao RiskManager, que pressupõe validação anterior. Exigir contrato de decisão e vínculo ao dataset aprovado antes de qualquer mutação; testar NaN, alvos invertidos, fonte ausente e reenvio. A contenção do CLI não corrige chamadas diretas à biblioteca. Responsável seguinte: Execução, com revisão de Qualidade.

CLI original preservado em `reports/paper-session-cli-before-review-20260914.txt`, SHA-256 `5e6a665e01f6863e990af601d72ada1890d8ba275ca680b71ed0d3885afe35e5`. Contenção reproduzida por2 testes que falhavam antes e passaram depois. Nenhum runner foi iniciado.

### Fila seguinte, ainda não executada

| Prioridade / responsável | Trabalho | Aceite |
|---|---|---|
| P0 Execução/Risco | Contrato único de sinal com proveniência antes de mutação | Inválido, NaN, alvo invertido ou não aprovado não alteram banco |
| P0 Dados/Integração | Cotação evidenciada e snapshot com leitura íntegra/atualização | Arquivo e banco vinculados; preço e horário reais; nenhuma mistura de estados |
| P1 Vulcan/Execução | Operação idempotente e outbox no mesmo commit do banco | Crash antes/depois do commit/publicação e replay não duplicam; CI Linux para concorrência |
| P1 Vulcan/Infra | Heartbeat dos ciclos realmente conectado ao bloqueio e telemetria | Worker crítico parado causa estado degradado e bloqueio; nenhuma garantia fixa sem medição |
| P1 Orion/Dados | Verificação do journal completo e relatórios exclusivos | Alterar identidade/tipo/tempo/payload é detectado; manifest confere bytes finais; sem sobrescrita |

Referências da revisão paper: `paper_session.py:295–300` e `357–369` (janela banco/journal); `coordinator.py:345` (garantias literais); `paper_session.py:103` e `446–463` (hash e persistência). Linhas referem-se ao HEAD revisado. Os testes de interrupção existentes não demonstram falha na janela entre commit e journal.

### Detalhamento para Dados/Integração

- `valuation_snapshot.py:215,239,315`: sobrescrita/INSERT OR REPLACE e leitura sem validar novamente conteúdo. `main.py:1360` confere arquivo, mas publicação pode usar payload SQLite diferente. Aceite: alterar saldo/posição mantendo equity/timestamps deve bloquear; arquivo e índice devem representar os mesmos bytes/identidade.
- `main.py:1382,1396` reaproveita evidência de patrimônio para outros campos e mescla banco atual. `main.py:954–960` associa posição por ticker. Aceite: resposta de uma única versão; identidade por trade; fechamento/reabertura do mesmo ticker não herda cotação antiga.
- `main.py:1333–1335` só produz snapshot quando nenhum existe. Aceite: versão nova explícita, recuperação após falha do feed e histórico separado de estado atual; nenhum snapshot indefinidamente fresco.

Esses três grupos não foram corrigidos nesta contenção. A lista vazia de aprovações segue sendo um bloqueio necessário, não prova de que a implementação suporta publicação confiável quando aprovada.

## Verificação

Antes das correções desta rodada:68 testes focais de snapshot, proveniência, candles e armazenamento passaram,1 aviso,5,34s. Não é a suíte completa nem atestado do dossiê. A sessão de teste anterior não estava mais acessível após a retomada, portanto seu resultado final não foi presumido.

Snapshot:4 falhas reproduzidas antes da correção;9 testes focais passaram depois (5 novos,4 legados). Preço escalar positivo, NaN, infinito e bool não são promovidos a cotação evidenciada. Posições ativas ficam sem avaliação válida até integração do contrato de cotação. Teste positivo de persistência/aprovação usa fixture sintética somente caixa; não representa aprovação financeira.

**Verificação final estabilizada:765 testes passaram,1 aviso,73,23s**, excluindo E2E. Uma execução anterior coletou testes legados durante a alteração e apresentou2 falhas; a repetição com arquivos estabilizados passou. CI Linux, frontend ao vivo e rentabilidade não foram certificados nesta rodada.
