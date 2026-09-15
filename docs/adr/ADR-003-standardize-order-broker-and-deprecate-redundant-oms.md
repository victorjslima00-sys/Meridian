# ADR-003: Padronização do Broker de Ordens e Depreciação de OMSs Redundantes

- **Status**: Proposto (Submetido para apreciação e ratificação institucional)
- **Data**: 2026-09-14
- **Autoridade Proponente**: SENTINEL (Gestão de Risco) / ANTIGRAVITY (Engenharia de Execução)
- **Decisores / Ratificadores**: Victor (Fundador), CEO Astra, NEXUS CSOO, Sentinel, Antigravity [Aguardando Deliberação]
- **Escopo**: `backend/app/agents/executor.py`, `backend/app/markets/`, `trading_bot/broker/`, `trading_bot/execution/`
- **Classificação**: Execução / Gestão de Ordens / Integridade Contábil
- **Ratification**: PENDING
- Ratification: PENDING

---

## 1. CURRENT STATE

A execução de ordens e a reconciliação patrimonial são o núcleo crítico da plataforma Meridian. Inconsistências nessa camada causam cálculos errôneos de patrimônio líquido (*equity*), violação de limites de risco e incapacidade de auditoria contábil.

No estado atual da base de código, o ecossistema Meridian acumulou **cinco modelos de ordens e abstrações de corretagem concorrentes**, operando de forma fragmentada:
- `ExecutorAgent` (`backend/app/agents/executor.py`): persistência em tabela `trades` SQLite com locking imediato e gestão atômica de `portfolio`.
- `PaperBroker` (`backend/app/markets/paper_broker.py`): implementa protocolo `Broker`, mas delega para `ExecutorAgent`.
- `CedroBroker` (`trading_bot/broker/cedro.py`): grava em tabela isolada `paper_trades` sem debitar saldo de caixa.
- `CedroClient` (`trading_bot/broker/cedro_client.py`): chamadas mock a URLs simuladas não autenticadas.
- `OrderManagementSystem` (`trading_bot/execution/order_manager.py`): OMS volátil em memória (`Dict[str, Order]`) sem comunicação com banco.

---

## 2. OBSERVED EVIDENCE

A auditoria empírica de código identificou o seguinte inventário de implementações concorrentes:

| Implementação | Localização no Código | Entidade de Ordem | Mecanismo de Persistência | Impacto no Saldo (`portfolio`) | Consumidor Ativo em Produção |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`ExecutorAgent`** | `backend/app/agents/executor.py` | Dict / linhas SQL diretas | SQLite tabela `trades` (`IMMEDIATE` lock) | Deduz e credita caixa atômico | **SIM** (API FastAPI, `ai_worker`, `exit_loop`) |
| **`PaperBroker`** | `backend/app/markets/paper_broker.py` | Implementa protocolo `Broker` | Delega para `ExecutorAgent` | Indireto | **NÃO** (Órfão em produção) |
| **`CedroBroker`** | `trading_bot/broker/cedro.py` | `@dataclass Order` (`broker/base.py`) | SQLite tabela `paper_trades` | **NÃO** afeta `portfolio` | Apenas script legado `fase2_paper_trading.py` |
| **`CedroClient`** | `trading_bot/broker/cedro_client.py` | Objetos JSON simulados | Nenhuma (chamadas mock a URLs falsas) | Nenhum | Nenhum |
| **`OrderManagementSystem`** | `trading_bot/execution/order_manager.py`| `@dataclass Order` com UUIDs | Memória volátil (`Dict[str, Order]`) | Nenhum | Apenas teste unitário `test_order_manager.py` |

### Fricções Graves Diagnosticadas Decorrentes da Fragmentação
1. **Descompasso Contábil entre Tabelas Concorrentes**:
   - `ExecutorAgent` grava na tabela `trades` e gerencia saldos na tabela `portfolio` com garantias transacionais e índice único parcial (`idx_trades_one_active_per_ticker`).
   - `CedroBroker` grava ordens em uma tabela isolada `paper_trades` sem debitar o saldo de caixa, gerando descompasso contábil se ambos os fluxos forem acionados.
2. **OMS Volátil Órfão (`OrderManagementSystem`)**:
   - O arquivo `trading_bot/execution/order_manager.py` implementa um OMS completo com estados (`PENDING`, `SUBMITTED`, `FILLED`, etc.) e controle de concorrência, mas mantém os dados em um dicionário em memória (`self.orders = {}`). Não se comunica com o banco de dados nem com o `ExecutorAgent`.
3. **Disparidade Crítica de Custos de Transação (Fricção B3)**:
   - Em **Pesquisa Quantitativa** (`trading_bot/data/model_evaluation.py`), desconta-se rigorosamente uma fricção de **10.0 bps por operação** (taxa de negociação B3, liquidação CBLC e slippage).
   - No **Motor de Backtest** (`trading_bot/backtest/engine.py`), aplica-se custo de *round-trip*.
   - No **Executor de Produção** (`backend/app/agents/executor.py:168`), o PnL é calculado como `((current_price - entry_price) / entry_price) * 100`, **sem deduzir nenhuma taxa de corretagem ou emolumento da B3**. As ordens de paper trading aparentam ser mais rentáveis do que o modelo matemático homologado em pesquisa.

---

## 3. DRIVERS DE DECISÃO (DECISION DRIVERS)

1. **Fonte Única de Verdade para Execução**: Unificar a contabilidade e a custódia de posições em um único repositório de dados com garantias ACID.
2. **Alinhamento Contábil de Fricção Financeira**: Garantir que as simulações em Paper Trading repliquem os custos operacionais da B3 (10.0 bps) previstos nos modelos de pesquisa.
3. **Persistência e Idempotência Absoluta**: Garantir que qualquer submissão de ordem possua um identificador de cliente determinístico (`clord_id`) gravado em disco com tolerância a quedas de processo.
4. **Preservação da Salvaguarda Financeira**: Manter a garantia incondicional `real_broker_calls == 0`.

---

## 4. OPÇÕES CONSIDERADAS

### Opção A: Manter os Vários Brokers para "Flexibilidade"
- *Vantagens*: Nenhum esforço imediato.
- *Desvantagens*: Risco inaceitável de desvio contábil, confusão de operadores e perda de consistência em auditorias financeiras.

### Opção B: Adotar o `OrderManagementSystem` em Memória como Núcleo
- *Vantagens*: Arquitetura orientada a objetos elegante com transições de estado explícitas.
- *Desvantagens*: Perda de persistência imediata em falhas de processo; reimplementaria de forma frágil o que o SQLite com WAL já faz com atomicidade robusta.

### Opção C (Recomendada): Padronização sobre Interface Canônica `IOrderBroker`, Promoção do `ExecutorAgent` e Depreciação de Módulos Órfãos
- *Vantagens*: Elimina código morto, consolida a persistência no SQLite já homologado, adiciona a taxa de fricção da B3 de 10 bps e estabelece um único modelo canônico de ordem.
- *Desvantagens*: Exige atualização de testes que dependiam das tabelas legadas `paper_trades` e do OMS in-memory.

---

## 5. PROPOSAL & RECOMMENDED OPTION

Recomenda-se formalmente a **Opção C**: Proposta para padronização da camada de corretagem e execução:

### 5.1. Definição Proposta do Contrato Canônico `IOrderBroker`
Em `trading_bot/core/interfaces.py` (ou `trading_bot/broker/canonical.py`), propõe-se estabelecer o contrato formal de corretagem:

```python
from typing import Protocol, Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"

@dataclass(frozen=True)
class CanonicalOrder:
    clord_id: str
    ticker: str
    side: OrderSide
    quantity: int
    price: float
    stop_loss: float
    take_profit: float
    status: OrderStatus
    created_at: str
    broker_ticket: Optional[str] = None
    fee_bps: float = 10.0

class IOrderBroker(Protocol):
    async def execute_buy(self, ticker: str, price: float, stop_loss: float, take_profit: float, capital_alloc: float) -> Dict[str, Any]: ...
    async def execute_sell(self, ticker: str, current_price: float, reason: str) -> Dict[str, Any]: ...
    def get_active_positions(self) -> List[Dict[str, Any]]: ...
    def get_cash_balance(self) -> float: ...
```

### 5.2. Promoção Proposta do `ExecutorAgent` como Engine Canônica
O `ExecutorAgent` (`backend/app/agents/executor.py`) é proposto como implementação de referência para Paper Trading, operando sobre o SQLite com locking imediato e WAL. O `PaperBroker` (`backend/app/markets/paper_broker.py`) será atualizado para aderir estritamente a `IOrderBroker`, atuando como fachada padronizada.

### 5.3. Descomissionamento Proposto dos Módulos Legados
1. Marcar como `@deprecated` e remover o agendamento do script `scripts/fase2_paper_trading.py`.
2. Remover a tabela isolada `paper_trades` das migrações do banco.
3. Descomissionar `trading_bot/broker/cedro.py`, `trading_bot/broker/cedro_client.py` e os mocks não autenticados.
4. Refatorar `trading_bot/execution/order_manager.py` para armazenar ordens na tabela SQLite permanente ou consolidar sua máquina de estados dentro de `ExecutorAgent`.

### 5.4. Incorporação Obrigatória de Custos da B3 no PnL
Proposta de modificação da rotina de encerramento de operações em `backend/app/agents/executor.py:168`:
```python
# Fórmula anterior (PnL Bruto irrealista):
# pnl_pct = ((current_price - entry_price) / entry_price) * 100

# Nova Fórmula Oficial Proposta (PnL Líquido com Fricção Institucional):
B3_FRICTION_RATE = 0.0010  # 10.0 bps (emolumentos B3 + liquidação CBLC)
gross_pnl_pct = ((current_price - entry_price) / entry_price)
net_pnl_pct = (gross_pnl_pct - (2 * B3_FRICTION_RATE)) * 100
pnl_reais = (current_price - entry_price) * shares - (entry_price * shares * B3_FRICTION_RATE) - (current_price * shares * B3_FRICTION_RATE)
```

---

## 6. CONSEQUÊNCIAS

### Consequências Positivas
- **Alinhamento entre Pesquisa e Execução**: O resultado de rentabilidade em Paper Trading passa a refletir fielmente o que foi calibrado nos modelos walk-forward de pesquisa quantitativa.
- **Segurança Contábil**: Fim do risco de dados órfãos na tabela `paper_trades`. Apenas uma tabela oficial (`trades`) e um registro de caixa (`portfolio`) mantêm a posição patrimonial.
- **Rastreabilidade e Idempotência**: Cada ordem enviada possui um identificador unívoco gravado de forma durável, impedindo execuções duplicadas acidentais.

### Consequências Negativas e Mitigações
- **Ajuste de Testes Existentes**: Testes que esperavam PnL bruto exato precisarão ser calibrados para o PnL líquido pós-fricção de 10 bps.
  - *Mitigação*: Atualizar as fixtures de teste para verificar tanto o PnL bruto quanto o líquido de emolumentos.

---

## 7. GOVERNANÇA E VERIFICAÇÃO (PROPOSTAS)

1. Executar auditoria de esquema no banco SQLite para confirmar ausência de referências a `paper_trades`.
2. Validar que toda execução em `ExecutorAgent` gera débito de taxas de 10.0 bps.
3. Verificar a invariante `real_broker_calls == 0` em todas as rotas e classes de corretagem.

---

## 8. DECISION PENDING

- **Status da Proposta**: PENDING
- **Ratification**: PENDING
- Ratification: PENDING
- **Observação**: Este documento é uma proposta técnica. Nenhuma alteração em `executor.py` ou em tabelas de corretagem deve ser executada sem autorização executiva expressa e deliberação institucional dos decisores.
