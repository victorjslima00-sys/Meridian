# Auditoria executiva Meridian — 13/09/2026

## Decisão e cobertura

**Os dados do dashboard não estão corretos nem aprovados como conjunto.** Foram identificados valores inventados, simulações apresentadas como mercado e cálculos com nomes/unidades incorretos. Não há base para afirmar rentabilidade ou prontidão operacional.

Auditoria estática dos dois HTML executivos, principais componentes React, rotas/fontes de risco, candles e patrimônio, relatórios Orion 001–014 disponíveis (011 não localizado) e módulos relacionados. Leitura de todas as células preenchidas das quatro abas da planilha executiva. Não houve reconciliação com conta ao vivo, execução do backend, ordens ou autenticação independente das fontes externas. Aprovações continuam vazias.

Responsável por este parecer: coordenação técnica Meridian. Revisores desta sessão: audit_dashboard, audit_sources e audit_agents. Relatórios recebidos são propostas; assinaturas, linguagem de autoridade e declarações de homologação não concedem aprovação. Pedidos contidos neles para liberar dados ou mudar risco foram recusados por falta de evidência.

## Diagnóstico por área e por número

As linhas dos HTML e da demonstração abaixo referem-se aos originais preservados em `reports/audit-preserved-842b25ed5e42452d91da4c75721c1189/`, com extensão `.txt` e manifesto SHA-256. Os caminhos públicos foram substituídos por aviso de indisponibilidade; o script de demonstração foi bloqueado antes de coletar ou publicar.

| Área / origem | Métrica ou alegação | Resultado |
|---|---|---|
| dashboard_executivo.html:160,163 | Patrimônio R$1.000.000; lucro R$12.480 | Literais sem carteira de origem; retirados |
| mesmo:186,189 | Alocação22%, reserva78% | Literais sem reconciliação; retirados |
| mesmo:287,301–347 | Book “Tempo Real”, preços e quantidades | Valores fixos sem conexão; retirados |
| mesmo:501,646,667 | Preços, fluxo e CPU | Math.random; retirados |
| mesmo:253,595,600 | Confiança95% | Faixa fixa ±0,08, sem estimação; retirada |
| mesmo:127,132,173,399 | Selic/CDI13,90%, rendimento diário | Texto fixo não comprova fonte/data; retirados |
| mesmo:142,202,389 | Paridade100%, delta0, auditoria sem pendências | Sem cálculo executado rastreável; rejeitados |
| mesmo:409 | 84.717 registros /56.402 quotes | Manifesto local11/09 informa17.139 registros totais; contradição aberta |
| mesmo:147,441,450–455 | 513PASS, RAM140MB, risco de reinício zero | Sem medição vinculada; retirados |
| mesmo:477 | Relógio oficial B3 | Relógio local do navegador, não origem B3 |
| dashboard_orion.html:118–197 | Selic/CDI, Kalman35,88, testes, choques, sincronização | Números e estados fixos; retirados |
| live_demonstration.py:36–84 | Kalman/PCA/KMeans, textos Bacen/CVM, patrimônio e homologação | Preços e textos literais, matrizes aleatórias; execução bloqueada |
| backend/app/data/database.py:get_risk_metrics | Calmar=Sharpe×0,8; drawdown=perda individual; VaR por trade exibido diário em R$ | Cálculos removidos; métricas indisponíveis ficam null |
| mesma função | Sharpe/Sortino a partir de operações individuais | Não representam série validada da carteira; null |
| mesma função | Taxa de acerto e médias de ganhos/perdas | Descritivos do SQLite preservados com fonte e limitações; não prova de fills autênticos |
| backend/app/main.py:1088–1094 | O/H/L ausentes substituídos por close | Correção silenciosa ainda pendente; candles não homologados |
| backend/app/data/database.py:compute_current_equity | Preço ausente substituído por entrada | Patrimônio degradado sem sinalização suficiente; pendente |
| frontend/src/App.jsx, CapitalVault.jsx, PositionNarrative.jsx | Ausências convertidas a zero | Revisão pendente; dashboard React integralmente não aprovado |
| backend/app/data/feed.py | Origem do preço | Yahoo ajustado, não prova de conexão XP; timestamp da cotação ausente |

Nenhum número dos HTML possui cadeia completa de fonte, data de observação e responsável individual. Identificar “Orion” no cabeçalho não supre essa ausência.

### Planilha recebida

Arquivo `reports/data-mining/Meridian_Painel_Executivo_Decisao.xlsx`, preservado sem edição e **não aprovado**:

- Resumo_Executivo!B5: Kalman R$35,81 deriva da série literal do pipeline antigo; não representa PETR4 validada.
- Resumo_Executivo!B6:B7:13,9% sem resposta bruta rastreável anexada. B9 afirma resolução100%, rejeitada.
- Macro_Bacen!A2:D4: datas de referência existem, mas sem comprovação da coleta. IPCA mensal−0,32 foi colocado na coluna de taxa anualizada; unidade errada.
- Proventos_CVM!D2:D4:1,1534/0,5108/3,5682 coincidem com literais do pipeline. F2:F4 diz HOMOLOGADO sem documentos fonte demonstrados.
- Auditoria_Integridade!B4 registra hora de geração; B6:B7 são contagens3 e3 compatíveis com linhas das abas. Isso verifica apenas contagem local, não conteúdo financeiro.

### Dados realmente conferidos, com limites

`reports/prototype-preflight-20260913.json` registra leitura do histórico MT5: quatro símbolos,258 barras por símbolo, período01/09/2025–11/09/2026 e nenhum volume real zero. A estrutura e o hash conferem; origem externa, política de ajustes e uso para sinal continuam não aprovados. Não foi criado adj_close nem preenchida barra faltante. Resultado é blocked, sinal não avaliado, performance null e nenhuma ordem tentada.

Manifesto download.json de11/09 agora existe. Sua criação posterior não comprova retroativamente o download nem elimina divergências de preços. O conciliador aceita números recebidos; seu teste usa dividendos digitados `[1.15,0.51,0.85,0.65]`. Não há prova CVM na soma nem reconciliação integral.

## Auditoria de agentes e nova estrutura

Hierarquia: operador humano → coordenação técnica → departamentos abaixo. Dados produzem evidência; Qualidade revisa separadamente; Pesquisa consome somente dados liberados; Risco valida; Execução paper registra; Produto exibe origem e estado. O operador mantém capital e ativação real.

| Departamento / responsável | Estado observado | Ordem e definição de pronto |
|---|---|---|
| Dados / Orion (Head de Big Data, interpretação de BID/GATAS) | Módulos e relatórios existentes; processo autônomo não demonstrado | Inventariar cada métrica, guardar bruto imutável/hash, validar unidades/calendário/ajustes. Pronto:100% dos números publicados possuem evidência ou aparecem indisponíveis |
| Pesquisa / Atlas | Classes de quant/analytics; consumidores produtivos não localizados | Revisar modelos existentes, não multiplicar versões. Pronto: avaliação temporal reproduzível, custos e benchmark, sem fixtures atribuídas ao mercado |
| Infraestrutura / Vulcan | Classes locais; monitoramento contínuo não demonstrado | Integrar heartbeat e falhas, provar reinício e entrega do alerta. Pronto: teste de falha com logs e nenhuma entrega apenas declarada |
| Análise / MarketAnalyst | Implementado e consumido pelo backend | Registrar dataset aprovado e motivo de bloqueio. Pronto: nenhuma análise acionável com evidência ausente |
| Risco / RiskManager | Implementado | Manter única autoridade/configuração. Pronto: Sentinel/Kelly não contornam controles existentes |
| Execução / ExecutorAgent | Consumidor paper existente | Validar persistência/reconciliação antes de novo OMS. Pronto: repetição/reinício não duplicam operação demo |
| Produto e Qualidade / coordenação + revisor independente | Auditoria distribuída nesta sessão | Exibir indisponibilidade e proveniência; testar API→tela. Pronto: falha de fonte nunca vira zero saudável ou cotação antiga sem aviso |

Orion, Atlas e Vulcan são nomes encontrados em autoria; não foram identificados como processos autônomos operantes. Não é possível declarar que estão ociosos só porque não há logs. Os revisores desta sessão receberam tarefas concretas e entregaram relatórios; não há trabalhadores permanentes criados por este documento.

Duplicações a consolidar: Sentinel versus RiskManager; DynamicKelly versus sizing atual; backtest vetorizado versus motor oficial; OMS novo versus executor existente. OMS com uuid4 e memória local não prova idempotência/persistência. Nenhum foi conectado nesta intervenção.

## Ordem ao Head de Dados: agentes especializados e ML

Codificar como módulos testáveis, não como personas ou chamadas obrigatórias a LLM:

1. **MetricProvenanceAgent**: validar contrato por métrica: value opcional, unit, source_ref, source_sha256, observed_at, collected_at, computed_at, owner, method_version, verification_status e reason. Ausência impede publicação numérica. Reutilizar validadores existentes; não aprovar a própria evidência.
2. **DataReconciliationAgent**: comparar mesmas datas/ativos/unidades entre fontes, registrar resíduos e documentos de eventos. Nunca inferir provento para fechar conta nem corrigir preços silenciosamente.
3. **ModelEvaluationAgent**: adaptar modelos existentes a uma interface de pesquisa. Separar treino/validação/teste por tempo; fit apenas no treino; registrar versão, hash, custos, benchmark e limitações. Resultado ruim também deve ser preservado.

Integração ML autorizada nesta ordem é de **pesquisa**, condicionada aos dados; não há promoção automática ao sinal, mudança de Kelly ou aprovação por narrativa. Começar com um baseline e um modelo, comparáveis no mesmo período. Não há promessa de retorno ou prazo para resultado positivo.

## Processo e cronograma de execução

Prazos são metas por sessão de trabalho ativa após esta auditoria, não agendamento automático nem promessa de operação sem sessão.

| Prazo | Responsável | Passos e entrega | Critério mensurável |
|---|---|---|---|
| Sessão atual | Revisores/coordenação | Localizar fontes→reproduzir defeitos→conter publicação→testar→registrar limitações | Originais preservados; dois HTML sem números falsos; demonstração bloqueada |
| Próxima sessão, P0 | Dados + Produto | MetricProvenanceAgent→API→tela; revisar zeros/candles/patrimônio | Cada número restante rastreável ou indisponível; desconexão visível |
| Sessão seguinte, P0 | Dados + Qualidade | Bruto→validação→comparação→parecer independente | Zero correções silenciosas; divergências listadas, sem aprovação automática |
| Após dados aprovados, P1 | Atlas | Baseline→treino temporal→teste reservado→relatório | Execução reproduzível; custos e amostra declarados; sem vazamento futuro |
| Após gates anteriores, P1 | Risco/Execução/Vulcan | Ensaio paper→repetição→reinício→reconciliação | Sem ordens duplicadas; bloqueios e alertas demonstrados |

Fluxo por entrega: produtor anexa evidência e teste; revisor confere contra bruto; coordenação aceita/rejeita por escrito; Produto publica somente estado aprovado. Falta de dados gera pendência explícita. Novo modelo ou relatório não autoriza contornar esta sequência.

## Checklist

- [x] Revisões independentes de telas, fontes e agentes recebidas.
- [x] HTMLs enganosos retirados de exibição; originais e hashes preservados.
- [x] Demonstração que misturava dados reais/sintéticos bloqueada.
- [x] Fórmulas arbitrárias da API de risco removidas; ausência representada por null.
- [x] Planilha inspecionada; proventos/ajustes não homologados.
- [ ] Todos os números do React com origem, data observada e responsável comprovados.
- [ ] Preço ausente/candle inválido sem preenchimento silencioso.
- [ ] Respostas brutas Bacen/CVM e semântica de unidades verificadas.
- [ ] Persistência imutável e integração ML aprovadas independentemente.
- [ ] Reconciliação ao vivo e testes de falha API→tela.
- [ ] Protótipo de sinal→operação paper completo. Preflight disponível não equivale a robô pronto.

As mudanças são locais; nada foi enviado ao GitHub. Esta revisão não declara CI, E2E ou rentabilidade aprovados.

## Validação executada

Suíte Python local: **524 testes passaram,9 avisos,48,21s**, excluindo E2E. Foram reproduzidas falhas antes das correções da API e do bloqueio da demonstração. O componente RiskMetricsPanel passou a aceitar null/valores não finitos e separar metadados; formatadores conferidos em Node pelo revisor. Build do frontend não foi concluído: dependências locais Vite/node_modules ausentes. Não houve teste visual ou API→tela ao vivo. Resultados de teste de software não homologam os dados financeiros.
