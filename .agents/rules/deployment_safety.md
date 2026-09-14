---
description: Travas de seguranca para operacoes de deploy, infraestrutura e publicacao em producao.
globs: ["**/*"]
always_on: true
---

# Governanca Institucional Meridian — Seguranca de Deploy e Producao (NEXUS-000C)

## 1. CI Verde e Pre-Requisito Necessario, mas NAO Autorizador de Producao
- A conclusao bem-sucedida de pipelines de CI atesta unicamente a corretude sintatica e logica dos testes automatizados.
- **CI VERDE != AUTORIZACAO DE PRODUCAO**.
- CI verde e **NECESSARIO**, porem **NAO E SUFICIENTE**.
- Contrato deterministico:
  ```
  SHA candidato (branch main)
        ↓
  CI desse MESMO SHA = SUCCESS (Pre-requisito deterministico obrigatorio)
        ↓
  Autorizacao executiva independente (Victor human gate + Astra audit ref)
        ↓
  Deploy em Producao
  ```
- Ausencia de evidencia de CI para o SHA exato a ser implantado resulta em bloqueio imediato (**FAIL-CLOSED**).

## 2. Modelo de Autorizacao de Producao (Victor + Astra)
A regra institucional estabelece que operacoes de producao exigem Victor + Astra:
- **Victor (Gate Humano Efetivo)**: Imposicao tecnica realizada via GitHub Environment `production` com **Required Reviewer** configurado para Victor. Nenhuma execucao prossegue sem a aprovacao humana direta na plataforma GitHub.
- **Astra (Referencia Executiva / Auditoria Institucional)**: Exigencia de identificador formal de autorizacao executiva (`astra_authorization_ref`) nos inputs do `workflow_dispatch`. Na infraestrutura atual, este mecanismo e de **AUDITORIA E RASTREABILIDADE INSTITUCIONAL (AUDIT-ONLY)**, nao havendo verificacao criptografica automatizada de assinatura nesta versao.
- **NEXUS (Autoridade Tecnico-Operacional)**: O identificador `nexus_directive_ref` fornece unicamente rastreabilidade tecnica da mudanca operacional. O NEXUS **NUNCA substitui** a autorizacao executiva de producao e este campo **NUNCA deve ser rotulado como autorizacao executiva**.

## 3. Desacoplamento Estrito e Protecao contra Script Injection
- O workflow `.github/workflows/deploy.yml` opera exclusivamente por disparo manual (`workflow_dispatch`).
- Gatilhos automaticos (`workflow_run`, `push`, `pull_request`) sao permanentemente proibidos para deploy.
- A confirmacao de producao utiliza um campo `choice` fechado (`CANCEL`, `DEPLOY-TO-PRODUCTION`), com default fail-safe `CANCEL`.
- Todos os inputs de workflow_dispatch e secrets sao tratados como nao confiaveis e transportados **exclusivamente via variaveis de ambiente (`env:`)**.
- E estritamente proibida a interpolacao de expressoes `${{ ... }}` diretamente dentro de blocos shell `run:`.
- Quoting seguro com `printf '%s\n'`, sem uso de `eval` ou construcao dinamica de comandos a partir de inputs.

## 4. Acoes Proibidas sob Diretivas Genericas
Nenhuma diretiva Nexus padrao autoriza automaticamente:
- Deploy em ambiente de producao live;
- Conexao de infraestrutura a mercados reais da B3 (`real_broker_calls == 0` inviolavel);
- Modificacao de infraestrutura em nuvem ativa (`terraform apply` em producao);
- Reinicializacao de servicos criticos de producao sem janela operacional;
- Alteracao de credenciais ou secrets de producao.
