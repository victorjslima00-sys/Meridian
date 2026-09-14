---
description: Invariantes inegociaveis de seguranca financeira, obrigatoriedade de paper trading e protecao contra risco real.
globs: ["**/*"]
always_on: true
---

# Governanca Institucional Meridian — Seguranca Financeira e Risco

## 1. Invariante Inegociavel: real_broker_calls == 0
- Ate autorizacao institucional futura explicita emitida pela Diretoria (Victor e CEO Astra), `real_broker_calls == 0` e uma invariante absoluta do sistema Meridian.
- O modo **Paper Trading** permanece estritamente obrigatorio em todas as execucoes e testes.
- Nenhum agente tem autoridade para ativar broker live por inferencia, extrapolacao ou conveniencia.
- Nenhum agente pode conectar capital financeiro real a infraestrutura de producao.

## 2. Principio Fail-Closed
- Nenhuma ausencia de dados pode ser interpretada automaticamente como "risco zero".
- Protecoes *fail-closed* nunca podem ser silenciosamente convertidas em *fail-open*.
- Se cotacoes, snapshots ou conexoes falharem, o comportamento obrigatorio e suspender novas operacoes (`HOLD`) e retornar valores patrimoniais como `null` ou `unavailable`.

## 3. Intocabilidade das Travas de Risco
- O `CircuitBreaker` (`trading_bot/risk/circuit_breaker.py`) nao pode ser bypassado, suprimido ou mockado para ignorar falhas reais.
- Guards de dimensionamento de posicao (`KellyFraction`, limites de alocacao) nunca devem ser relaxados ou deletados para fazer testes passarem.
- **SENTINEL** (autoridade institucional de risco) mantem poder de veto pleno em qualquer decisao que afete a seguranca patrimonial.
