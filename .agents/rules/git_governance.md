---
description: Governanca e boas praticas para operacoes Git, protegendo o historico e garantindo rastreabilidade.
globs: ["**/*"]
always_on: true
---

# Governanca Institucional Meridian — Git e Versionamento

## 1. Operacoes Terminantemente Proibidas
- `git push --force` ou `git push -f` em qualquer branch remota.
- `--force-with-lease` sem autorizacao institucional especifica.
- Rebase destrutivo sobre historico compartilhado.
- Apagar branches arbitrariamente sem consentimento.
- `git reset --hard` destrutivo sobre trabalho nao preservado.
- Modificar a branch `main` diretamente em alteracao material sem revisao ou PR.
- Esconder testes falhos ou apagar testes para forcar CI verde.

## 2. Padrao Operacional Preferido
- **Branch por diretiva**: Cada tarefa ou diretiva Nexus deve rodar em branch dedicada:
  - Formato: `nexus/<directive>-<descricao>` (ex: `nexus/000-governance-bootstrap`).
- **Commits atomicos**: Commits pequenos, descritivos e com explicacao tecnica clara.
- **Rollback simples**: Manter diff auditavel e reversivel a qualquer momento.
- **Verificacao local antes do push**: Rodar suite de testes e tripwire de segredos localmente antes de submeter commits.
- **Sem merge automatico**: Nunca forcar merge direto em `main` sem que todos os checks obrigatorios estejam verdes.
