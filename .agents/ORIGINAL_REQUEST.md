# Original User Request

## Initial Request — 2026-07-08T00:49:16Z

# Teamwork Project Prompt — Draft

> Status: Ready for launch — awaiting user approval
> Goal: Craft prompt → get user approval → delegate to teamwork_preview

Sistema de swing trading B3 automatizado (Meridian) com execução via corretora Cedro, exigindo alta cobertura de testes e implementação estrita das regras de gestão de risco.

Working directory: /Users/mac/.gemini/antigravity/scratch/meridian
Integrity mode: development

## Requirements

### R1. Aplicar Correções Críticas e CI (Tarefa A)
Garantir que o repositório passe na integração contínua. Substituir o workflow atual do GitHub Actions por um novo `.github/workflows/ci.yml` configurado com Python 3.11/3.12, `flake8` (erros críticos E9, F63, F7, F82) e `pytest` com cobertura. Confirmar se as correções do motor de backtest (bug do `ROUND_TRIP`) já estão aplicadas.

### R2. Elevar Cobertura de Testes (Tarefa B)
Alcançar pelo menos 70% de cobertura nos módulos principais. Focar nos stubs vazios de `tests/test_engine.py`, em `data/validator.py`, `data/cross_validation.py`, `data/ingestion.py`, `backtest/metrics.py`, `core/config.py` e `core/clock.py`. Não utilizar stubs falsos; escrever validações reais de lógica (ex: mocks para chamadas de API externa).

### R3. Atualizar Documentação (Tarefa C)
Sincronizar o README com o estado real do projeto, removendo pendências já resolvidas (como o capital inicial que já está no settings) e documentar o status da cobertura de testes por módulo.

### R4. Consolidar Gestão de Risco (Tarefa D)
Garantir que o sistema de dimensionamento de posição (Kelly) exista de forma isolada em `risk/` ou `execution/` para ser usado ao vivo, não apenas no engine de backtest. Confirmar a existência de um gerador de matriz de retornos para o `check_correlation`. Implementar logger, integração Telegram e scheduler em `core/` caso estejam faltando.

### R5. Limpeza de Código (Tarefa E)
Resolver avisos menores identificados (ex: uso desnecessário de `global` no cache do IBOV, DeprecationWarnings do SQLite3 e imports não utilizados).

### R6. Invariantes de Segurança
O bot operará com dinheiro real no futuro. Manter estritamente: confirmação manual via Telegram como padrão, timeout gerando rejeição, circuit breaker não-contornável e obrigatoriedade de paper trading. Não mockar credenciais em código.

## Acceptance Criteria

### Verificação Objetiva e Estrita
- [ ] `pytest tests/ --cov=trading_bot --cov-report=term-missing -v` roda com 100% dos testes passando.
- [ ] Nenhum teste consiste apenas em stubs vazios (`pass`).
- [ ] `flake8 . --select=E9,F63,F7,F82` roda sem apontar novos erros (além de possíveis cosméticos).
- [ ] `python scripts/fase1_backtest.py` roda de ponta a ponta sem lançar exceções.
- [ ] Commits realizados são pequenos, descritivos e separados por tarefa (sem "big ball of mud").
