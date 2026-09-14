# Meridian — revisão e delegação de 14/09/2026

## Feedback técnico

Há progresso real: armazenamento com criação exclusiva e inventário de hashes, endpoint de candles que rejeita dados inválidos, contrato de proveniência e integração inicial às APIs. São implementações verificáveis, não evidência de retorno financeiro. Os registros de aprovação de dados e métricas continuam vazios.

A primeira suíte local desta sessão passou:639 testes,8 avisos,123,41s, sem E2E. Esse resultado precede as correções descritas abaixo e não substitui a verificação final delas. Não foi acionada operação real nem iniciado o worker pelo coordenador.

Foram encontrados defeitos de integração apesar dos testes verdes: campos monetários brutos continuavam presentes quando o estado dizia unavailable; frontend convertia null em zero; tooltip podia interpretar hash como aprovação. Esses defeitos receberam tarefas de correção, não somente pareceres.

## Funções efetivamente delegadas nesta sessão

| Agente | Responsabilidade e arquivos | Entrega / critério |
|---|---|---|
| review_integration_today | API de patrimônio e posições em backend/app/main.py; testes correspondentes | Reprovar valores sem evidência em todos os campos, não apenas alias value. Remover fallback100 e timestamps de observação inventados. Testar retorno null sem alterar risco |
| review_ui_today | App.jsx, PositionNarrative.jsx e ProvenanceTooltip.jsx | Null não vira zero, lucro ou aprovação. Conexão encaminhada ao cofre. Rótulo de verificado só com estado explícito verified. Testes de regressão e build disponível |
| fix_bacen_units | Minerador Bacen e testes | Anualização somente para séries diárias11/12; meta432 já anual; IPCA433 mensal não anualizado. Datas/valores inválidos rejeitados por lote. Mudança de contrato documentada |
| Coordenação | Revisão, integração, plano visual e registro | Confrontar arquivos com relatórios; registrar testes e limitações; não aceitar auto-homologação |

Os nomes acima identificam tarefas desta sessão, não serviços permanentes. As alterações em .agents vistas no status Git são preexistentes a esta revisão; não foram usadas como ordens nem modificadas pelo coordenador.

## O que ainda impede o protótipo completo

1. **Snapshot de avaliação persistente (P0):** carteira, cada cotação e seus horários reais precisam de evidência imutável. Hash de banco mutável e horário da requisição não substituem isso. Enquanto faltar, publicação monetária permanece indisponível.
2. **Dados aprovados (P0):** divergências MT5/COTAHIST e ajustes precisam de documentação primária. Um manifesto criado depois ou um teste aritmético não resolvem a origem dos preços.
3. **Integração visual (P0):** comprovar API→tela com dados disponíveis/indisponíveis, desconexão e reconexão; HTTP200 sozinho não significa dado aprovado.
4. **Pesquisa (P1):** avaliador/modelos são pesquisa. O script evaluate_research_models.py gera série sintética; seus resultados não representam desempenho B3. Não executar nem publicar esse exemplo como validação de rentabilidade.
5. **Ciclo paper (P1):** integrar sinal→RiskManager→executor existente→registro→reconciliação; testar repetição/reinício. Não multiplicar motores de risco/OMS para substituir integração ausente.

## Próximos tickets, por ordem e dependência

- **Dados + Integração, próximo lote:** SnapshotValuation — preservar conjunto exato de posições/saldos/cotações, unidade, horário observado e coleta; calcular por identificador estável. Aprovação liga-se ao snapshot, não a cada acesso à API. Pronto: reconsulta reproduz resultado, fonte ausente bloqueia, nenhum uso de entry_price para fingir preço atual.
- **Qualidade, junto ao próximo lote:** MetricIdentity — incluir nome estável da métrica no vínculo de aprovação e consumir o horário real da evidência. Pronto: aprovação de uma métrica não serve para outra e não depende de now a cada request.
- **Dados, lote seguinte:** persistir bytes brutos Bacen e referências CVM no armazenamento revisado; hash em atributos de DataFrame ainda não é arquivo durável. Pronto: fonte pode ser reinspecionada e reprovação preservada.
- **Pesquisa/Atlas, após fontes:** corrigir e validar contrato temporal/reconciliação antes de avaliar baseline/modelo com dados aprovados. Pronto: teste fora da amostra sem informação futura, custos e resultados negativos preservados.
- **Execução + Infra/Vulcan, após gates:** sessão paper reproduzível com eventos persistentes, interrupção e repetição sem duplicação. Pronto: relatório de uma sessão completa; nenhum envio real.

Prazos significam lotes de trabalho ativo dependentes das evidências, não datas automáticas. O próximo marco de produto é uma sessão paper auditável; não há percentual objetivo de conclusão nem prazo prometido para lucro.
