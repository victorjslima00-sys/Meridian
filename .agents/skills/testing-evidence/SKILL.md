---
name: testing-evidence
description: Protocolo formal de coleta e apresentacao de evidencias de testes e integridade antes de declarar conclusao de tarefas de engenharia. Use sempre que for concluir uma diretiva ou implementacao.
---

# Skill: Evidencia de Testes e Integridade

Esta skill estabelece os criterios objetivos que tornam uma tarefa verificavel sob a governanca Meridian.

## Principio Fundamental
- *"Funcionou para mim"* NAO e evidencia.
- *"O CI passou anteriormente"* NAO prova que o codigo atual esta correto.
- Sucesso exige teste executado sobre a arvore de arquivos atual, com resultado observavel e auditavel.

## Checklist Obrigatorio de Evidencias

Antes de reportar a conclusao de qualquer trabalho, o agente deve registrar:

1. **Comandos Executados**: Linha de comando exata utilizada no terminal.
2. **Suite de Testes**: Arquivos de teste rodados (ex: `pytest tests/test_coordinator.py`).
3. **Contabilidade de Resultados**:
   - `passed`: quantidade exata.
   - `failed`: quantidade exata (deve ser 0 para conclusao).
   - `skipped`: quantidade exata e justificativa para cada skip.
4. **Lint e Tipagem**: Status de `flake8` e/ou `oxlint` (zero erros criticos).
5. **Diff Auditavel**: Resumo de `git diff --stat` comprovando apenas mudancas autorizadas.
6. **Branch e Commit**: Branch ativa e hash SHA-1 do commit gerado.
7. **Invariantes Verificadas**:
   - `real_broker_calls == 0`: comprovado por inspecao/testes.
   - Zero segredos em disco rastreado: comprovado por `test_seguranca_segredos.py`.
   - `main` intocada diretamente: comprovado por `git branch`.
8. **Pendencias Conhecidas**: Lista honesta de limitacoes ou dividas tecnicas remanescentes.
