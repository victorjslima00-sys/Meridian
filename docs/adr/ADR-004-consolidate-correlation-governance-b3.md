# ADR-004: Consolidação da Governança de Correlação e Alinhamento com Ativos B3

- **Status**: Proposto (Submetido para ratificação institucional)
- **Data**: 2026-09-14
- **Autoridade Responsável**: SENTINEL (Governança de Risco Institucional)
- **Decisores**: Victor (Fundador), CEO Astra, NEXUS CSOO, Sentinel, Antigravity
- **Escopo**: `backend/app/agents/risk_manager.py`, `trading_bot/risk/correlation.py`, `trading_bot/risk/circuit_breaker.py`
- **Classificação**: Gestão de Risco / Controle de Exposição / Análise Quantitativa

---

## 1. Contexto e Formulação do Problema

Um dos princípios basilares da gestão de risco em carteiras quantitativas é a limitação de concentração em ativos correlacionados. Operar simultaneamente posições compradas em múltiplos papéis com alta correlação (por exemplo, PETR4 e PRIO3 no setor de óleo & gás, ou ITUB4, BBDC4 e BBAS3 no setor financeiro) multiplica a exposição ao risco sistêmico e viola os limites prudenciais de drawdown máximo.

A auditoria arquitetural empírica diagnosticada em setembro de 2026 revelou uma desconexão crítica e uma anomalia severa no subsistema de controle de correlação do Meridian:

### 1.1. As Anomalias Empíricas Diagnosticadas

1. **Grupo de Correlação Hardcoded de Criptomoedas em Bot de Ações B3**:
   No arquivo `backend/app/agents/risk_manager.py` (linhas 5-8), encontra-se a seguinte declaração:
   ```python
   CORRELATED_GROUPS: List[List[str]] = [
       ["BTC-USD", "ETH-USD"],  # Crypto major → correlação 90%+
   ]
   ```
   **O Problema**: A plataforma Meridian destina-se exclusivamente a ações da B3 (mercado acionário brasileiro). O gestor de risco em produção verifica apenas se o ativo pertence ao par `BTC-USD` / `ETH-USD`. Para todo o universo de ações da B3 (ex.: PETR4, VALE3, BBAS3), **a checagem de correlação é totalmente inócua e sempre aprova novas compras**.

2. **Fragmentação e Desalocação de Funções Matemáticas**:
   - O arquivo `trading_bot/risk/correlation.py` implementa unicamente a função `build_returns_matrix(tickers, start, end)`. Não contém cálculo de coeficiente de correlação nem lógica de veto.
   - A lógica matemática real de cálculo da correlação de Pearson (`numpy.corrcoef`) e a função `check_correlation(candidate_ticker, open_tickers, returns_matrix, correlation_max=0.7)` foram implementadas no arquivo de Circuit Breakers (`trading_bot/risk/circuit_breaker.py`, linha 171).

3. **Desconexão Operacional em Tempo de Execução**:
   - A função `check_correlation` em `circuit_breaker.py` é testada isoladamente em testes unitários, mas **nunca é invocada pelo `RiskManager` nem pelos workers da API**.
   - O sistema opera em produção sem qualquer governança quantitativa real sobre correlação setorial de ações brasileiras.

---

## 2. Drivers de Decisão (Decision Drivers)

1. **Eficácia de Risco no Universo B3**: As salvaguardas de correlação devem atuar sobre os ativos reais negociados na bolsa brasileira, calculando matrizes dinâmicas de retornos diários.
2. **Coesão e Localização de Código**: Todas as rotinas matemáticas de retornos, covariância e correlação de Pearson devem residir no módulo coeso `trading_bot/risk/correlation.py`.
3. **Fail-Closed em Ausência de Dados**: Caso o histórico de preços de um ativo candidato ou de ativos já em custódia seja insuficiente para estimar uma correlação estatisticamente significante, a ordem deve ser preventivamente bloqueada.
4. **Parametrização Institucional**: O limiar máximo de correlação aceitável ($\rho_{\max} = 0.70$) deve ser parametrizado e auditável.

---

## 3. Opções Consideradas

### Opção A: Manter Listas Estáticas de Grupos Setoriais da B3
- Exemplo: Criar listas fixas como `["PETR4", "PRIO3", "RECV3"]`, `["ITUB4", "BBDC4", "BBAS3", "SANB11"]`.
- *Vantagens*: Implementação simples sem overhead computacional de matrizes.
- *Desvantagens*: Rígida, exige manutenção manual constante, ignora descorrelações conjunturais e não captura correlações cruzadas entre setores distintos em cenários de estresse de mercado.

### Opção B: Cálculo Dinâmico em Tempo Real sem Salvaguarda de Histórico Mínimo
- *Vantagens*: Totalmente automatizado via cotações recentes.
- *Desvantagens*: Ativos recém-listados (IPOs) ou com falhas de ingestão geram matrizes singulares ou coeficientes espúrios, podendo aprovar ordens indevidas.

### Opção C (Escolhida): Mapeamento Dinâmico de Pearson com Validação Fail-Closed e Consolidação em `correlation.py`
- *Vantagens*: Matemático, adaptativo ao mercado real da B3, fail-closed por desenho e elimina anomalias de criptomoedas.
- *Desvantagens*: Requer acesso aos retornos dos últimos 60 pregões no momento do pré-trade check.

---

## 4. Decisão Arquitetural

Adota-se formalmente a **Opção C**. Fica estabelecida a reestruturação da governança de correlação:

### 4.1. Unificação do Módulo `trading_bot/risk/correlation.py`
1. Mover a função `check_correlation` de `trading_bot/risk/circuit_breaker.py` para `trading_bot/risk/correlation.py`.
2. Em `circuit_breaker.py`, manter apenas um alias de compatibilidade com aviso de depreciação durante o período de transição:
   ```python
   # Em trading_bot/risk/circuit_breaker.py:
   from trading_bot.risk.correlation import check_correlation  # Backward compatibility
   ```

### 4.2. Algoritmo Padronizado em `trading_bot/risk/correlation.py`
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

### 4.3. Integração com `backend/app/agents/risk_manager.py`
1. Remover a constante `CORRELATED_GROUPS = [["BTC-USD", "ETH-USD"]]`.
2. No método `RiskManager.evaluate_trade()`, carregar os preços dos últimos 60 pregões a partir do banco de dados/feed de mercado e invocar `evaluate_portfolio_correlation`.
3. Se o retorno for desaprovado, emitir rejeição com código de auditoria `REJECTED_BY_CORRELATION_CEILING`.

---

## 5. Consequências

### 5.1. Consequências Positivas
- **Proteção Real para a Carteira B3**: Impede a alavancagem inadvertida em setores concentrados (ex.: compra simultânea de PETR4 e PRIO3 durante choque do petróleo).
- **Eliminação de Código Ilusório**: Fim das referências irrelevantes a pares de criptomoedas em um sistema operacional de ações brasileiras.
- **Fail-Closed Rigoroso**: Garantia de que ativos ilíquidos ou com histórico corrompido não sejam admitidos na carteira.

### 5.2. Consequências Negativas e Mitigações
- **Custo Computacional Adicional**: Cálculo de matrizes de correlação durante a triagem de sinais.
  - *Mitigação*: Cachear a matriz de retornos diários dos tickers do universo B3 monitorado com TTL de 1 hora, uma vez que os preços de fechamento diários mudam apenas uma vez por dia.

---

## 6. Governança e Critérios de Aceite

1. Eliminação total de `BTC-USD` e `ETH-USD` do codebase de produção.
2. Teste unitário em `tests/test_correlation.py` cobrindo cenários:
   - Ativo altamente correlacionado ($\rho > 0.70$) é vetado.
   - Ativo descorrelacionado ($\rho \le 0.70$) é aprovado.
   - Histórico curto (< 30 pregões) ou retorno com NaN resulta em veto *fail-closed*.
3. Verificação de que nenhuma chamada a corretora real é feita (`real_broker_calls == 0`).
