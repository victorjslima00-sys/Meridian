---
name: nexus-directive
description: Procedimento padrao para ingestao, validacao contra o repositorio, execucao tecnica e geracao de relatorio de Diretivas NEXUS. Use sempre que receber uma instrucao contendo cabeçalho MERIDIAN — NEXUS DIRECTIVE ou marcadores equivalentes.
---

# Skill: Processamento de Diretivas NEXUS

Esta skill orienta o Antigravity no processamento rigoroso de especificacoes tecnico-operacionais emitidas pelo **NEXUS (CSOO)**.

## Protocolo de Execucao em 10 Etapas

### 1. Identificar a Diretiva
- Extrair o identificador formal da diretiva (ex: `NEXUS-000`, `NEXUS-001`).
- Identificar prioridade (`P0`, `P1`, `P2`) e escopo institucional.

### 2. Extrair o Objetivo Tecnico
- Definir com precisao o que deve ser entregue.
- Mapear a secao *"NÃO FAZER"* para delimitar estritamente o escopo proibido.

### 3. Extrair Invariantes Inegociaveis
- Identificar todas as restricoes inviolaveis (ex: `real_broker_calls == 0`, `fail-closed`, integridade criptografica de dados).

### 4. Mapear Arquivos e Modulos Provaveis
- Identificar quais caminhos de codigo, documentacao e configuracao serao afetados.

### 5. Validar Premissas contra a HEAD do Repositorio
- Inspecionar os arquivos reais, contratos e testes no disco.
- Nunca assumir que premissas da diretiva estao corretas sem verificacao previa.

### 6. Tratar Divergencias (se houver)
- Se qualquer premissa estiver desatualizada ou incorreta, emitir o bloco padrao:
  ```text
  NEXUS DEVIATION DETECTED
  Premissa recebida: [...]
  Realidade encontrada: [...]
  Evidencia: [arquivo/teste]
  Impacto: [...]
  Alternativa recomendada: [...]
  ```
- Adaptar com seguranca se a intencao for preservavel; pausar e reportar se alterar risco ou escopo.

### 7. Selecionar o Regime de Execucao
- Adotar o modo compativel (conforme regra `antigravity_mode_policy.md`).

### 8. Implementar Estritamente o Escopo Autorizado
- Modificar apenas os arquivos autorizados pela diretiva.
- Nao aplicar refatoracoes cosmeticas ou melhorias nao solicitadas.

### 9. Executar Testes e Coletar Evidencias
- Executar testes automatizados relevantes.
- Executar suite de regressao e tripwire de segredos (`tests/test_seguranca_segredos.py`).
- Registrar metricas reais de passed, failed e skipped.

### 10. Gerar Relatorio Final Padronizado do Nexus
- Concluir a execucao com o modelo exato exigido na diretiva (`NEXUS IMPLEMENTATION REPORT`).
