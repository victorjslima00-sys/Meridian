# ADR-004: Consolidação da Governança de Correlação e Alinhamento com Ativos B3

- **Status**: Proposto (Submetido para apreciação e ratificação institucional)
- **Data**: 2026-09-14
- **Autoridade Proponente**: SENTINEL (Governança de Risco Institucional)
- **Decisores / Ratificadores**: Victor (Fundador), CEO Astra, NEXUS CSOO, Sentinel, Antigravity [Aguardando Deliberação]
- **Escopo**: `backend/app/agents/risk_manager.py`, `trading_bot/risk/correlation.py`, `trading_bot/risk/circuit_breaker.py`
- **Classificação**: Gestão de Risco / Controle de Exposição / Análise Quantitativa
- **Ratification**: PENDING
- Ratification: PENDING

---

## 1. CURRENT STATE

Um dos princípios basilares da gestão de risco em carteiras quantitativas é a limitação de concentração em ativos correlacionados. Operar simultaneamente posições compradas em múltiplos papéis com alta correlação (por exemplo, PETR4 e PRIO3 no setor de óleo & gás, ou ITUB4, BBDC4 e BBAS3 no setor financeiro) multiplica a exposição ao risco sistêmico e viola os limites prudenciais de drawdown máximo.

No estado atual da base de código, a plataforma Meridian destina-se exclusivamente a ações da B3 (mercado acionário brasileiro), porém a governança de correlação encontra-se desconectada do runtime e com anomalias de escopo.

---

## 2. OBSERVED EVIDENCE

A auditoria arquitetural empírica diagnosticada em setembro de 2026 revelou as seguintes evidências objetivas:

1. **Grupo de Correlação Hardcoded de Criptomoedas em Bot de Ações B3**:
   No arquivo `backend/app/agents/risk_manager.py` (linhas 5-8), encontra-se a seguinte declaração:
   ```python
   CORRELATED_GROUPS: List[List[str]] = [
       ["BTC-USD", "ETH-USD"],  # Crypto major -> correlação 90%+
   ]
   ```
   **Diagnóstico**: O gestor de risco em produção verifica apenas se o ativo pertence ao par `BTC-USD` / `ETH-USD`. Para todo o universo de ações da B3 (ex.: PETR4, VALE3, BBAS3), **a checagem de correlação é inócua e sempre aprova novas compras**.

2. **Fragmentação e Desalocação de Funções Matemáticas**:
   - O arquivo `trading_bot/risk/correlation.py` implementa unicamente a função `build_returns_matrix(tickers, start, end)`. Não contém cálculo de coeficiente de correlação nem lógica de veto.
   - A lógica matemática real de cálculo da correlação de Pearson (`numpy.corrcoef`) e a função `check_correlation(candidate_ticker, open_tickers, returns_matrix, correlation_max=0.7)` foram implementadas no arquivo de Circuit Breakers (`trading_bot/risk/circuit_breaker.py`, linha 171).

3. **Desconexão Operacional em Tempo de Execução**:
   - A função `check_correlation` em `circuit_breaker.py` é testada isoladamente em testes unitários, mas **nunca é invocada pelo `RiskManager` nem pelos workers da API**.
   - O sistema opera em produção sem qualquer governança quantitativa real sobre correlação setorial de ações brasileiras.

---

## 3. DRIVERS DE DECISÃO (DECISION DRIVERS)

1. **Eficácia de Risco no Universo B3**: As salvaguardas de correlação devem atuar sobre os ativos reais negociados na bolsa brasileira, calculando matrizes dinâmicas de retornos diários.
2. **Coesão e Localização de Código**: Todas as rotinas matemáticas de retornos, covariância e correlação de Pearson devem residir no módulo coeso `trading_bot/risk/correlation.py`.
3. **Fail-Closed em Ausência de Dados**: Caso o histórico de preços de um ativo candidato ou de ativos já em custódia seja insuficiente para estimar uma correlação estatisticamente significante, a ordem deve ser preventivamente bloqueada.
4. **Parametrização Institucional**: O limiar máximo de correlação aceitável ($\rho_{\max} = 0.70$) deve ser parametrizado e auditável.

---

## 4. OPÇÕES CONSIDERADAS

### Opção A: Manter Listas Estáticas de Grupos Setoriais da B3
- Exemplo: Criar listas fixas como `["PETR4", "PRIO3", "RECV3"]`, `["ITUB4", "BBDC4", "BBAS3", "SANB11"]`.
- *Vantagens*: Implementação simples sem overhead computacional de matrizes.
- *Desvantagens*: Rígida, exige manutenção manual constante, ignora descorrelações conjunturais e não captura correlações cruzadas entre setores distintos em cenários de estresse de mercado.

### Opção B: Cálculo Dinâmico em Tempo Real sem Salvaguarda de Histórico Mínimo
- *Vantagens*: Totalmente automatizado via cotações recentes.
- *Desvantagens*: Ativos recém-listados (IPOs) ou com falhas de ingestão geram matrizes singulares ou coeficientes espúrios, podendo aprovar ordens indevidas.

### Opção C (Recomendada): Mapeamento Dinâmico de Pearson com Validação Fail-Closed e Consolidação em `correlation.py`
- *Vantagens*: Matemático, adaptativo ao mercado real da B3, fail-closed por desenho e elimina anomalias de criptomoedas.
- *Desvantagens*: Requer acesso aos retornos dos últimos 60 pregões no momento do pré-trade check.

---

## 5. PROPOSAL & RECOMMENDED OPTION

Recomenda-se formalmente a **Opção C**: Proposta de reestruturação da governança de correlação:

### 5.1. Unificação Proposta do Módulo `trading_bot/risk/correlation.py`
1. Mover a função `check_correlation` de `trading_bot/risk/circuit_breaker.py` para `trading_bot/risk/correlation.py`.
2. Em `circuit_breaker.py`, manter apenas um alias de compatibilidade com aviso de depreciação durante o período de transição:
   ```python
   # Em trading_bot/risk/circuit_breaker.py:
   from trading_bot.risk.correlation import check_correlation  # Backward compatibility
   ```

### 5.2. Algoritmo Padronizado Proposto em `trading_bot/risk/correlation.py`
```python
import numpy as np
import pandas as pd
from typing import List, Tuple

MINIMUM_TRADING_DAYS_FOR_CORRELATION = 30
DEFAULT_MAX_CORRELATION = 0.70

def evaluate_portfolio_correlation(
    candidate_ticker: str,
    open_tickers: List[str],
    returns_matrix: pd.DataFrame,
    correlation_max: float = DEFAULT_MAX_CORRELATION,
) -> Tuple[bool, str, float]:
    """
    Avalia se o ativo candidato excede o teto de correlação com qualquer ativo em custódia.
    Retorna: (is_approved, reason, highest_correlation_observed)
    """
    if not open_tickers:
        return True, "PORTFOLIO_EMPTY", 0.0

    if candidate_ticker in open_tickers:
        return False, f"DUPLICATE_TICKER: {candidate_ticker} ja possui posicao aberta", 1.0

    # Salvaguarda fail-closed: verifica se há dados suficientes
    if candidate_ticker not in returns_matrix.columns:
        return False, f"CORRELATION_FAIL_CLOSED: {candidate_ticker} ausente na matriz de retornos", 1.0

    if len(returns_matrix) < MINIMUM_TRADING_DAYS_FOR_CORRELATION:
        return False, f"CORRELATION_FAIL_CLOSED: amostra historica inferior a {MINIMUM_TRADING_DAYS_FOR_CORRELATION} pregoes", 1.0

    candidate_returns = returns_matrix[candidate_ticker].dropna()
    if len(candidate_returns) < MINIMUM_TRADING_DAYS_FOR_CORRELATION:
        return False, f"CORRELATION_FAIL_CLOSED: dados validos insuficientes para {candidate_ticker}", 1.0

    max_corr = -1.0
    violating_ticker = None

    for active in open_tickers:
        if active not in returns_matrix.columns:
            # Se um ativo já em carteira não tem retornos, falha fechado
            return False, f"CORRELATION_FAIL_CLOSED: ativo em carteira {active} sem retornos", 1.0
            
        active_returns = returns_matrix[active].dropna()
        # Interseção temporal estrita
        aligned = pd.concat([candidate_returns, active_returns], axis=1, join="inner")
        if len(aligned) < MINIMUM_TRADING_DAYS_FOR_CORRELATION:
            return False, f"CORRELATION_FAIL_CLOSED: intersecao de datas insuficiente entre {candidate_ticker} e {active}", 1.0
            
        corr_matrix = np.corrcoef(aligned.iloc[:, 0], aligned.iloc[:, 1])
        corr_coef = float(corr_matrix[0, 1])

        if np.isnan(corr_coef):
            return False, f"CORRELATION_FAIL_CLOSED: NaN detectado na correlacao entre {candidate_ticker} e {active}", 1.0

        if corr_coef > max_corr:
            max_corr = corr_coef
            violating_ticker = active

        if corr_coef > correlation_max:
            return False, f"HIGH_CORRELATION: {candidate_ticker} tem correlacao {corr_coef:.2f} com {active} (max {correlation_max:.2f})", corr_coef

    return True, f"CORRELATION_APPROVED: max observada {max_corr:.2f}", max_corr
```

### 5.3. Integração Proposta com `backend/app/agents/risk_manager.py`
Substituir a lista obsoleta `CORRELATED_GROUPS` pela chamada a `evaluate_portfolio_correlation`, injetando a matriz de retornos construída a partir do cache de cotações B3.

---

## 6. CONSEQUÊNCIAS

### Consequências Positivas
- **Proteção Real contra Concentração**: Elimina falsos negativos em ativos brasileiros; bloqueia novas compras quando a carteira já possuir papéis do mesmo setor altamente correlacionados.
- **Princípio Fail-Closed**: Ausência de cotações históricas suficientes veta preventivamente a ordem.
- **Racionalização de Código**: Centraliza rotinas de correlação no pacote quantitativo coeso `trading_bot/risk/correlation.py`.

### Consequências Negativas e Mitigações
- **Dependência de Dados Históricos**: Requer no mínimo 30 pregões de dados alinhados para todos os ativos em análise.
  - *Mitigação*: Cache local de retornos no SQLite e ingestão diária via CotaHist/YFinance.

---

## 7. GOVERNANÇA E CRITÉRIOS DE VERIFICAÇÃO (PROPOSTOS)

1. Teste unitário comprovando que correlações superiores a 0.70 bloqueiam a ordem com motivo detalhado.
2. Teste de fail-closed garantindo que ativos com histórico curto ou sem dados retornam rejeição preventiva.
3. Auditoria de código confirmando remoção completa de referências a `BTC-USD` e `ETH-USD` no gestor de ações B3.

---

## 8. DECISION PENDING

- **Status da Proposta**: PENDING
- **Ratification**: PENDING
- Ratification: PENDING
- **Observação**: Este documento é uma proposta técnica. Nenhuma alteração no arquivo financeiro `risk_manager.py` deve ser executada nesta diretiva, em cumprimento estrito às salvaguardas institucionais de isolamento de risco.
