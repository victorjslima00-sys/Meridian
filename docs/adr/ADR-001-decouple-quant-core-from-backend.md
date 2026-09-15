# ADR-001: Desacoplamento do Núcleo Quantitativo (`trading_bot`) da Camada Web (`backend.app`)

- **Status**: Proposto (Submetido para apreciação e ratificação institucional)
- **Data**: 2026-09-14
- **Autoridade Proponente**: NEXUS CSOO / ANTIGRAVITY (Engenharia de Software)
- **Decisores / Ratificadores**: Victor (Fundador), CEO Astra, NEXUS CSOO, Sentinel (Risco) [Aguardando Deliberação]
- **Escopo**: `trading_bot/`, `backend/app/`
- **Classificação**: Arquitetura de Software / Modularidade / Governança de Dependências
- **Ratification**: PENDING
- Ratification: PENDING

---

## 1. CURRENT STATE

A especificação fundacional do projeto Meridian estabelece uma separação conceitual de responsabilidades em duas camadas primárias:
1. **Núcleo Quantitativo e de Execução (`trading_bot/`)**: biblioteca contendo algoritmos de backtest, motores de sinais, avaliação temporal de modelos, circuit breakers e conectores de mercado.
2. **Camada de Entrega e Aplicação (`backend/app/`)**: serviço web em FastAPI responsável pela exposição de rotas REST, autenticação, persistência relacional (SQLite), orquestração de workers assíncronos e supervisão operacional.

No estado atual da base de código, as dependências não fluem exclusivamente de fora para dentro (`backend/app` $\longrightarrow$ `trading_bot`). Em vez disso, verificam-se importações ativas do núcleo quantitativo para o backend da aplicação, gerando acoplamento bidirecional.

---

## 2. OBSERVED EVIDENCE

A auditoria arquitetural realizada em setembro de 2026 (`MERIDIAN-ARCH-AUDIT-20260914-WS-D`) identificou **7 importações diretas e ativas** do núcleo quantitativo para o backend:

| Arquivo de Origem (`trading_bot/`) | Linha | Importação Detectada | Módulo de Destino (`backend/app/`) |
| :--- | :--- | :--- | :--- |
| `trading_bot/core/coordinator.py` | 28 | `from backend.app.data.database import now_b3` | `backend/app/data/database.py` |
| `trading_bot/core/coordinator.py` | 67 | `from backend.app.worker_state import LoopSupervisionState` | `backend/app/worker_state.py` |
| `trading_bot/risk/circuit_breaker.py` | 111 | `from backend.app.data.database import compute_current_equity, get_equity_refs` | `backend/app/data/database.py` |
| `trading_bot/data/valuation_snapshot.py` | 111 | `from backend.app.data.feed import get_current_price` | `backend/app/data/feed.py` |
| `trading_bot/execution/paper_session.py` | 27 | `from backend.app.agents.executor import ExecutorAgent` | `backend/app/agents/executor.py` |
| `trading_bot/execution/paper_session.py` | 28 | `from backend.app.agents.risk_manager import RiskManager` | `backend/app/agents/risk_manager.py` |
| `trading_bot/execution/paper_session.py` | 29 | `from backend.app.data.database import DB_PATH` | `backend/app/data/database.py` |

Simultaneamente, o backend importa dezenas de símbolos essenciais de `trading_bot` (`CircuitBreaker`, `CentralCoordinator`, `TelegramNotifier`, `get_latest_valuation_snapshot`, `calculate_position_size`, `MetricProvenanceAgent`).

### Impactos Operacionais Diagnosticados
1. **Acoplamento Circular e Fragilidade em Tempo de Execução**: A inicialização mútua dos módulos causa `ImportError: cannot import name ... from partially initialized module`. Para contornar essa falha, os desenvolvedores adotaram *lazy imports* (importações tardias declaradas dentro de métodos e funções, ex.: linhas 111 de `circuit_breaker.py` e `valuation_snapshot.py`).
2. **Degradação de Performance em Loops Críticos**: As importações tardias são executadas a cada iteração de loops assíncronos (por exemplo, a cada ciclo de 5 segundos do `exit_loop`).
3. **Incapacidade de Distribuição Modular**: O pacote `trading_bot` não pode ser empacotado como uma biblioteca independente nem reutilizado em ambientes serverless ou pipelines locais sem carregar todo o framework FastAPI e Starlette.
4. **Cegueira em Análise Estática**: Ferramentas de tipagem e verificação estática (`mypy`, `pyright`, `flake8`) perdem a capacidade de validar árvores de dependência completas devido a imports dinâmicos dentro do corpo de rotinas.

---

## 3. DRIVERS DE DECISÃO (DECISION DRIVERS)

1. **Modularidade e Reusabilidade**: `trading_bot` deve ser uma biblioteca matemática e de execução 100% autocontida, com dependências limitadas a pacotes científicos padrão (NumPy, Pandas, SciPy, Pydantic).
2. **Eliminação de Imports Circulares**: Erradicação total de dependências cruzadas e de *lazy imports* defensivos.
3. **Inversão de Controle (IoC) e Injeção de Dependências**: Subsistemas de risco e coordenação devem operar sobre contratos abstratos (`Protocols` / interfaces), recebendo adaptadores de persistência e feeds via injeção de dependência no momento da inicialização.
4. **Preservação de Invariantes de Integridade**: Zero impacto na garantia `real_broker_calls == 0` e no isolamento transacional de snapshots criptográficos.

---

## 4. OPÇÕES CONSIDERADAS

### Opção A: Manter os Lazy Imports com Documentação
- *Vantagens*: Risco imediato zero; nenhuma alteração de código necessária.
- *Desvantagens*: Mantém a dívida técnica acumulada, impede a tipagem estática rigorosa e perpetua o risco de regressões misteriosas de ciclo de importação em refatorações futuras.

### Opção B: Mover Todo o Código de `trading_bot` para dentro de `backend/app`
- *Vantagens*: Unifica a árvore de imports sob uma raiz única.
- *Desvantagens*: Destrói a separação arquitetural da plataforma, transformando o repositório em um monólito web acoplado, impedindo o uso do motor quantitativo em pipelines autônomos de pesquisa e HPC.

### Opção C (Recomendada): Refatoração por Inversão de Controle (IoC), Extração de Interfaces e Camada de Domínio Compartilhada
- *Vantagens*: Resolve a causa raiz do acoplamento, viabiliza tipagem estática estrita, permite testes unitários com mocks limpos e viabiliza a publicação de `trading_bot` como pacote autônomo.
- *Desvantagens*: Requer refatoração cuidadosa dos construtores de `CircuitBreaker`, `CentralCoordinator` e `PaperSessionRunner`.

---

## 5. PROPOSAL & RECOMMENDED OPTION

Recomenda-se formalmente a **Opção C**. Regra proposta para ratificação institucional:

> **REGRA ARQUITETURAL #1 (Proposta para Ratificação)**:  
> O namespace `trading_bot` **NÃO DEVE IMPORTAR** de `backend`. Toda comunicação e provimento de serviços do backend para o núcleo quantitativo deve ocorrer através de interfaces abstratas implementadas pelo backend e injetadas no `trading_bot` via inversão de controle.

### Plano de Implementação Estrutural Proposto

#### 1. Realocação de Utilitários de Domínio Neutros
- Migrar funções temporais neutras como `now_b3()` de `backend/app/data/database.py` para `trading_bot/core/clock.py`.
- `trading_bot/core/clock.py` passa a ser a fonte canônica do horário oficial da B3 (`America/Sao_Paulo`). O backend importa `now_b3` de `trading_bot.core.clock`.

#### 2. Definição de Interfaces de Dados (`Protocols`)
Criar em `trading_bot/core/interfaces.py` as abstrações estruturais (utilizando `typing.Protocol`):
```python
from typing import Protocol, Tuple, Optional

class IEquityDataProvider(Protocol):
    def compute_current_equity(self) -> float: ...
    def get_equity_refs(self) -> Tuple[float, float, float]: ...

class IPriceFeed(Protocol):
    def get_current_price(self, ticker: str) -> Optional[float]: ...

class IWorkerStateObserver(Protocol):
    def notify_worker_event(self, event_name: str, details: dict) -> None: ...
```

#### 3. Injeção de Dependências no Circuit Breaker
Refatorar `CircuitBreaker` (`trading_bot/risk/circuit_breaker.py`):
```python
class CircuitBreaker:
    def __init__(
        self,
        config: Optional[RiskConfig] = None,
        equity_provider: Optional[IEquityDataProvider] = None,
    ):
        self.config = config or RiskConfig()
        self.equity_provider = equity_provider
```
Quando instanciado dentro do backend (`backend/app/main.py`), o backend injeta uma instância de adaptador que encapsula as chamadas a `compute_current_equity` e `get_equity_refs` do SQLite.

#### 4. Isolamento do `CentralCoordinator`
Substituir o import de `backend.app.worker_state.LoopSupervisionState` em `trading_bot/core/coordinator.py` por uma estrutura de dados de evento de domínio nativa (`CoordinatorWorkerState`) interna a `trading_bot/core/coordinator.py`. O backend traduz seus estados de supervisão para os tipos do coordenador.

#### 5. Isolamento de `valuation_snapshot.py`
Injetar o `IPriceFeed` na rotina de cálculo de valuation em vez de importar `backend.app.data.feed.get_current_price` estaticamente.

---

## 6. CONSEQUÊNCIAS

### Consequências Positivas
- **Desacoplamento Rigoroso**: O grafo de dependências torna-se uma árvore acíclica direcionada (DAG): `backend` $\longrightarrow$ `trading_bot` $\longrightarrow$ `core/interfaces`.
- **Eliminação de Lazy Imports**: Todas as importações voltam ao topo dos arquivos (`PEP 8`), permitindo análise estática com 100% de precisão por `flake8`, `mypy` e IDEs.
- **Testabilidade Aprimorada**: Testes unitários do `CircuitBreaker` e `Coordinator` podem ser executados sem necessidade de banco de dados SQLite ou do framework FastAPI, reduzindo o tempo de execução da suíte de testes.
- **Portabilidade Institucional**: `trading_bot` poderá ser compilado e distribuído em contêineres mínimos de pesquisa ou execução local (ex.: bridge com MetaTrader 5 sem overhead web).

### Consequências Negativas e Mitigações
- **Custo de Refatoração Inicial**: Demanda atualização dos pontos de chamada onde `CircuitBreaker` e `CentralCoordinator` são instanciados.
  - *Mitigação*: Implementar defaults opcionais retrocompatíveis com avisos de depreciação durante a fase de transição.
- **Verbozidade de Injeção**: Exige código explícito de amarração (*wiring*) na inicialização da aplicação (`lifespan`).
  - *Mitigação*: Centralizar a injeção em um módulo container ou factory de inicialização (`backend/app/container.py`).

---

## 7. GOVERNANÇA E VERIFICAÇÃO AUTOMATIZADA

Para garantir que a regra arquitetural não sofra regressão após ratificação, deve ser introduzido um teste de tripwire automatizado em `tests/test_architecture_contracts.py`:

```python
import ast
from pathlib import Path

def test_trading_bot_never_imports_backend():
    trading_bot_dir = Path("trading_bot")
    violations = []
    for py_file in trading_bot_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("backend"):
                        violations.append(f"{py_file}:{node.lineno} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("backend"):
                    violations.append(f"{py_file}:{node.lineno} imports from {node.module}")
    assert not violations, f"Regra de Inversão de Dependência violada: {violations}"
```

---

## 8. DECISION PENDING

- **Status da Proposta**: PENDING
- **Ratification**: PENDING
- Ratification: PENDING
- **Observação**: Este documento constitui recomendação técnica da engenharia e aguarda deliberação e ratificação institucional colegiada (Victor, Astra, Nexus, Sentinel) antes de qualquer implementação no código-fonte.
