---
description: Diretrizes mandatórias de integridade de dados, governança fail-closed e apresentação institucional para a Meridian Technologies.
globs: ["**/*"]
always_on: true
---

# Diretrizes Mandatórias de Integridade e Governança Meridian

## 1. Tolerância Zero com Dados Fictícios ou Simulados
- É terminantemente proibido exibir dados simulados, fictícios, números aleatórios (`Math.random()`), patrimônios ilustrativos (ex: "R$ 1.000.000") ou livros de ofertas artificiais como se fossem informações de mercado reais.
- Se uma métrica ou cotação não possui fonte rastreável com hash SHA-256 e data observada comprovada, ela DEVE ser apresentada como `null` ou com o aviso explícito de `INDISPONÍVEL`.

## 2. Vedação Absoluta a Correções Silenciosas de Dados
- Nunca preencha ou interpole dados faltantes em silêncio (ex: substituir Open/High/Low zerados pelo Close).
- Na ocorrência de dados ausentes, incompletos ou corrompidos, a resposta técnica obrigatória é o bloqueio imediato com retorno de erro HTTP explícito (ex: 502/503) e registro de status `MISSING_DATA` ou `UNEXPLAINED_MISMATCH`.

## 3. Separação Estrita de Governança (Sem Auto-Homologação)
- Relatórios de engenharia e quantitativos são propostas técnicas; nenhuma assinatura ou declaração de engenharia concede aprovação operacional.
- Aprovações de dados e alterações de risco são prerrogativas exclusivas da coordenação e revisores independentes nos arquivos separados de governança (`config/metric_approvals.json` e `config/data_approvals.json`).
- O assistente NUNCA deve solicitar ou forçar o relaxamento de travas de risco da CEO Astra.

## 4. Eficiência Local e Zero Custos Ocultos
- Todos os motores matemáticos quantitativos devem rodar localmente na CPU em Pure NumPy, respeitando os limites da máquina (Intel Core i5, 8 GB RAM, sem GPU).
- Fontes externas devem ser estritamente dados públicos gratuitos do Governo Federal (Bacen SGS / CVM Open Data), deixando sempre cristalino ao usuário que nenhuma API comercial paga é exigida.

## 5. Padrão Estético e Linguagem Institucional de Alta Renda
- Painéis e saídas visuais devem adotar a linguagem e estética de terminais financeiros institucionais de primeira linha (Bloomberg Terminal, BTG Alpha, XP Institutional Desk).
- Utilizar números tabulares alinhados (`tabular-nums`), métricas financeiras precisas (AUM, Mark-to-Market, Hurdle Rate Selic) e banir layouts genéricos com aparência de "SaaS amador".
