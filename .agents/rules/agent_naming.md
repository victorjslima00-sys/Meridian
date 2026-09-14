---
description: Desambiguacao mandatoria entre a autoridade institucional SENTINEL e componentes internos do Antigravity.
globs: ["**/*"]
always_on: true
---

# Governanca Institucional Meridian — Convencao de Nomes de Agentes

## 1. Distincao entre Autoridade Institucional e Framework
A Meridian Technologies possui uma autoridade independente de gestao de risco denominada:
- **SENTINEL**: Mandato executivo de risco, com poder de veto independente sobre operacoes financeiras e conformidade institucional.

Se o ambiente do Antigravity ou seu subsistema Teamwork possuir internamente um agente, papel ou arquiteto tambem denominado "sentinel":
- Qualquer mencao ao componente interno da ferramenta DEVE utilizar o identificador: **`AGY-Teamwork-Sentinel`**.

## 2. Vedacao de Ambiguidade
- E terminantemente proibido escrever em relatorios executivos ou tecnicos declaracoes ambiguas como:
  > *"Sentinel aprovou"*
- Sempre explicitar se a acao refere-se a autoridade institucional de risco (`SENTINEL`) ou ao componente de orquestracao interno do assistente (`AGY-Teamwork-Sentinel`).
