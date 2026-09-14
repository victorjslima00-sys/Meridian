---
description: Travas de seguranca para operacoes de deploy, infraestrutura e publicacao em producao.
globs: ["**/*"]
always_on: true
---

# Governanca Institucional Meridian — Seguranca de Deploy e Producao

## 1. CI Verde Nao e Autorizacao de Producao
- A conclusao bem-sucedida de pipelines de CI/CD atesta unicamente a corretude sintatica e logica dos testes automatizados.
- **CI VERDE != AUTORIZACAO DE PRODUCAO**.

## 2. Acoes Proibidas sob Diretivas Genericas
Nenhuma diretiva Nexus padrao autoriza automaticamente:
- Deploy em ambiente de producao live;
- Conexao de infraestrutura a mercados reais da B3;
- Modificacao de infraestrutura em nuvem ativa (Terraform apply em producao);
- Reinicializacao de servicos criticos de producao sem janela operacional;
- Alteracao de credenciais ou secrets de producao.

## 3. Autorizacao Formal
Qualquer acao envolvendo implantacao live requer autorizacao explicita, documentada e com duplo aval da autoridade humana (Victor) e da Diretoria Executiva (Astra).

## 4. Desacoplamento Estrito de Deploy e Contrato de Producao (NEXUS-000D)
- O pipeline `.github/workflows/deploy.yml` opera exclusivamente por disparo manual (`workflow_dispatch`) na branch `main`.
- Gatilhos automaticos (`workflow_run`, `push`, `pull_request`) estao terminantemente abolidos para producao.
- **Same-SHA Main CI Prerequisite**: Exige evidencia deterministica de execucao bem-sucedida do workflow `ci.yml` associada ao mesmo SHA, na branch `main` e evento `push`.
- **Validacao Exaustiva de Secrets**: Todos os 8 secrets mandatorios (`SERVER_IP`, `SSH_PRIVATE_KEY`, `SSH_KNOWN_HOSTS`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `EMERGENCY_PASSWORD`, `API_KEY`, `ALLOWED_ORIGINS`) sao validados com fail-closed antes de qualquer conexao SSH ou rsync.
- **SSH Host Authenticity**: Proibido `ssh-keyscan` dinamico (TOFU). Exige `SSH_KNOWN_HOSTS` previamente conhecido e fixado. Mismatch resulta em fail-closed.
- **Seguranca de Transporte SSH**: Segredos sao transmitidos remotamente via stdin pipe (`cat > /app/Meridian/.env`) com `umask 077` e `chmod 600`, NUNCA como argumentos na linha de comando (`argv`).
- **Papeis de Governanca**:
  - `Victor (Required Reviewer)`: Portao humano tecnicamente imposto pelo GitHub Environment `production`.
  - `Astra (astra_authorization_ref)`: Identificador auditavel da autorizacao executiva formal (AUDIT-ONLY).
  - `Nexus (nexus_directive_ref)`: Rastreabilidade tecnico-operacional da mudanca.
