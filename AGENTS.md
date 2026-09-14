# Meridian Technologies — Governanca Institucional e Arquitetura de Agentes

**Diretoria Executiva**: CEO Astra (GPT-6 ASTRA)  
**Coordenacao Tecnico-Operacional**: NEXUS CSOO (GPT-5.6 Sol)  
**Camada de Engenharia e Execucao**: Antigravity  
**Autoridade Humana**: Victor (Fundador)  

---

## 1. Estrutura de Governanca Institucional
A Meridian opera com separacao estrita de funcoes e responsabilidades:
1. **Victor (Humano)**: Autoridade final. Pode pausar, vetar ou redirecionar qualquer diretiva.
2. **CEO Astra (Executivo)**: Estrategia institucional, alocacao de recursos e apetite de risco.
3. **NEXUS CSOO (Arquitetura & Governanca)**: Contratos, especificacoes tecnicas, CI/CD e confiabilidade.
4. **ANTIGRAVITY (Engenharia)**: Inspecao de realidade, implementacao de codigo, testes e evidencias.
5. **SENTINEL (Risco)**: Veto independente sobre qualquer operacao financeira ou de risco.

---

## 2. Invariantes Inegociaveis
- **Paper Trading Obrigatorio**: `real_broker_calls == 0`. Nenhuma ordem real e enviada a corretoras.
- **Fail-Closed**: Dados ausentes ou inconsistentes resultam em bloqueio de operacoes e exibicao de `null`/`unavailable`.
- **Integridade Criptografica**: Nenhuma metrica financeira e publicada sem hash SHA-256 e evidencia rastreavel.
- **Circuit Breaker Intocavel**: Limite de perda diaria (3%) e drawdown maximo (8%) nunca podem ser desativados.
- **Seguranca de Segredos**: Zero credenciais em disco versionado (`tests/test_seguranca_segredos.py` 100% verde).

---

## 3. Catalogo de Regras Ativas (`.agents/rules/`)
- [nexus_authority.md](.agents/rules/nexus_authority.md): Funcao CSOO, hierarquia institucional e protocolo de desvios.
- [financial_safety.md](.agents/rules/financial_safety.md): Invariante `real_broker_calls == 0` e travas de risco.
- [git_governance.md](.agents/rules/git_governance.md): Proibicao de force push e convencoes de branch por diretiva.
- [secret_safety.md](.agents/rules/secret_safety.md): Tolerancia zero com exposicao de chaves e senhas.
- [deployment_safety.md](.agents/rules/deployment_safety.md): CI verde != autorizacao de producao.
- [learn_policy.md](.agents/rules/learn_policy.md): Fluxo institucional para revisao de aprendizados (/learn).
- [agent_naming.md](.agents/rules/agent_naming.md): Desambiguacao mandatoria entre SENTINEL e AGY-Teamwork-Sentinel.
- [antigravity_mode_policy.md](.agents/rules/antigravity_mode_policy.md): Selecao do regime operacional (/boost, /teamwork, /goal).
- [meridian_data_governance.md](.agents/rules/meridian_data_governance.md): Diretrizes de dados sem simulacoes ficticias.

---

## 4. Catalogo de Skills Ativas (`.agents/skills/`)
- `nexus-directive`: Ingestao e execucao formal de diretivas do NEXUS em 10 etapas.
- `testing-evidence`: Protocolo de verificacao objetiva e contabilidade de testes antes de conclusao.

---

## 5. Guardrails e Hooks (`.agents/hooks.json`)
- `nexus-safety-guard`: Hook `PreToolUse` para interceptacao deterministica de force push, operacoes destrutivas e ativacao de live broker.
