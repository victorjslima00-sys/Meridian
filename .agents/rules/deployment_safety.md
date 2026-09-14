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

## 4. Desacoplamento Estrito de Deploy (NEXUS-000B)
- O pipeline `.github/workflows/deploy.yml` opera exclusivamente por disparo manual (`workflow_dispatch`).
- Nenhum gatilho automático (`workflow_run`, `push`, `pull_request`) é permitido para produção.
- Requer autorização identificável (`nexus_directive_ref`) e confirmação inequívoca (`confirmation: DEPLOY-TO-PRODUCTION`).
