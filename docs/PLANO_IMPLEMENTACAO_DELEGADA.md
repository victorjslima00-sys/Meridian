# Entregas delegadas para o Meridian funcionar

Ordem do operador: implementar, com divisão de trabalho e economia de contexto. Escopo operacional: pesquisa e simulação; nenhuma execução real liberada. Plano iniciado em 13/09/2026. Prazos abaixo são marcos por sessão ativa, não tarefas agendadas.

## Lote atual — três implementadores e uma integração

| Responsável ativo | Entrega de código | Critério de aceitação |
|---|---|---|
| build_storage — Dados/Orion | Armazenamento sem sobrescrita, contenção dos caminhos e conferência de hashes | Tentativa de substituir dado falha sem mudar original; arquivo adulterado/manifesto ausente gera erro no inventário |
| build_candles — API/Produto | Endpoint de candles rejeita OHLC inválido em vez de copiar fechamento | Nenhuma série parcial ou preço preenchido; dados válidos preservados; erro explícito |
| audit_sources — Qualidade | MetricProvenanceAgent determinístico | Número só publicável com evidência íntegra e aprovação administrativa independente; ausências ficam null |
| Coordenação técnica | Revisar contratos, integração e suíte completa | Registrar resultados medidos, limites e pendências; não promover dados por teste unitário |

Cada implementador possui arquivos específicos para evitar conflitos. Bugfix começa por teste que falha; depois correção e teste focal. Aprovação final exige revisão independente do código e testes completos. Nomes Orion/Produto/Qualidade identificam responsabilidades; os IDs acima são os agentes efetivamente acionados nesta sessão.

## Próximos lotes e dependências

1. **API→dashboard (P0, próximo lote):** aplicar contrato de proveniência às métricas; distinguir último recebimento de timestamp do dado; corrigir patrimônio com preço ausente; testar API/tela e desconexão. Responsáveis: Dados, Produto e Qualidade. Pronto quando cada valor tiver fonte/data/unidade ou estado indisponível e nenhuma substituição silenciosa.
2. **Fontes para estratégia (P0):** corrigir periodicidades Bacen e preservar resposta bruta; reconciliar OHLC e eventos com evidências primárias. Responsável: Dados/Orion. Pronto quando conjunto temporal e transformações tiverem parecer independente; divergência não resolvida permanece bloqueada.
3. **Baseline e ML de pesquisa (P1, depende de2):** Atlas integra um modelo existente ao mesmo experimento do baseline, com treino anterior ao teste, custos e benchmark. Pronto quando resultado for reproduzível e reportar também falhas; nenhum requisito de lucro garantido.
4. **Ciclo paper (P1, depende de1–3):** Análise→Risco→Executor existente→registro persistente→reconciliação. Vulcan testa interrupção/reinício e alertas. Pronto quando repetição não duplicar operação e falha de fonte bloquear nova entrada.

## Regras de integração

- Não criar nova autoridade de risco em paralelo ao RiskManager; não substituir Kelly por declaração de relatório.
- Não criar outro OMS antes de provar que o executor existente não atende ao ciclo paper.
- Não chamar algo de ao vivo sem conexão e timestamp observados.
- Hash confere integridade local; não autentica origem nem comprova previsão.
- Testes usam fixtures sintéticas identificadas e nunca geram métricas executivas de mercado.
- Alterações continuam locais, sem modificar aprovações de dados, capital ou modo de execução.

O lote atual remove defeitos necessários à operação confiável. Não conclui por si só o fluxo sinal→operação paper nem a integração visual.
