# ADR-005: Saneamento de Configurações Fantasma e Formalização de Schemas

- **Status**: Proposto (Submetido para ratificação institucional)
- **Data**: 2026-09-14
- **Autoridade Responsável**: NEXUS CSOO / ANTIGRAVITY (Engenharia de Plataforma)
- **Decisores**: Victor (Fundador), CEO Astra, NEXUS CSOO, Sentinel, Antigravity
- **Escopo**: `config/settings.yaml`, `backend/app/runtime_config.py`, `trading_bot/core/config.py`
- **Classificação**: Governança de Configuração / Qualidade de Software / Confiabilidade

---

## 1. Contexto e Formulação do Problema

Arquivos de configuração declarativos (como `config/settings.yaml`) constituem o contrato primário entre operadores de infraestrutura, gestores de risco e o código executável de uma plataforma de negociação algorítmica.

A auditoria arquitetural empírica diagnosticada em setembro de 2026 identificou **duas fragilidades graves na camada de configuração do Meridian**:

### 1.1. Configurações Fantasma e Desconectadas
Uma varredura automatizada contra todo o código-fonte identificou que pelo menos **12 chaves e blocos inteiros de configuração declarados em `config/settings.yaml` não possuem qualquer consumidor ativo**:

| Chave em `config/settings.yaml` | Valor Declarado | Ocorrências no Código | Diagnóstico Empírico |
| :--- | :--- | :--- | :--- |
| `data.brapi_base_url` | `"https://brapi.dev/api"` | 0 referências | A classe `cross_validation.py` utiliza URL codificada em string fixa. |
| `data.rate_limit.requests_per_month` | `15000` | 0 referências | Nenhuma rotina monitora nem impõe cota mensal de chamadas. |
| `data.rate_limit.retry_max_attempts` | `3` | 0 referências | Retries de rede não respeitam este parâmetro. |
| `data.rate_limit.retry_backoff_seconds` | `2.0` | 0 referências | Backoff não utiliza esta variável. |
| `data.cache_days` | `5` | 0 referências | O cache de dados históricos do SQLite não consome este threshold. |
| `data.storage.redis_url` | `"${REDIS_URI}"` | 1 classe órfã | `trading_bot/data/storage.py` declara `RedisCacheL2`, que **nunca é instanciada**. |
| `signals.target_pct` | `0.10` | 0 referências | O motor `signals/engine.py` utiliza exclusivamente múltiplos de ATR (`target_atr_mult`). |
| `execution.confirmation_timeout_minutes`| `10` | 1 script legado | Apenas o script legado `fase2_paper_trading.py` lia este valor. A API e o coordenador o ignoram. |
| `broker.poll_interval_seconds` | `300` | 0 referências | Nenhuma tarefa de polling consome este parâmetro. |
| `broker.base_url` | `"https://cedrotech.com/..."` | 0 referências | `cedro_client.py` ignora a configuração e hardcoda rotas de teste. |
| `genetic_optimizer.*` | Bloco completo | 0 referências | Não existe qualquer otimizador genético implementado no repositório. |
| `llm.failure_policy` | `"technical_fallback"` | 1 leitura cosmética | `RuntimeConfig` valida a string, mas o runtime sempre força o fail-closed `HOLD`. |

### 1.2. Riscos Operacionais das Configurações Fantasma
1. **Falsa Sensação de Segurança e Controle**: Um operador que altere `data.rate_limit.requests_per_month` ou `signals.target_pct` acredita estar ajustando o comportamento do bot, quando na realidade o sistema ignora a mudança silenciosamente.
2. **Ausência de Validação de Chaves Desconhecidas**: Erros de digitação cometidos por operadores no YAML (ex.: `max_drwdown` em vez de `max_drawdown`) não lançam exceção na inicialização; o sistema apenas adota valores default silenciosamente, o que viola o princípio *fail-fast*.

---

## 2. Drivers de Decisão (Decision Drivers)

1. **Paridade Absoluta entre Configuração e Código**: Toda chave presente em `config/settings.yaml` deve ter um consumidor ativo e testado. Toda chave órfã deve ser purgada.
2. **Validação Estrita com Falha Rápida (*Fail-Fast*)**: A aplicação deve recusar-se a inicializar caso o arquivo de configuração contenha chaves desconhecidas (`extra="forbid"`), tipos incorretos ou valores fora dos limites prudenciais.
3. **Imutabilidade e Tipagem Estática**: Acesso tipado através de modelos Pydantic v2 validados, abolindo dicionários genéricos e chamadas soltas a `.get("chave", default)`.
4. **Verificação de Limites Financeiros**: Validação semântica matemática de parâmetros de risco no momento da inicialização.

---

## 3. Opções Consideradas

### Opção A: Manter as Chaves Órfãs para "Expansão Futura"
- *Vantagens*: Nenhuma alteração no YAML.
- *Desvantagens*: Perpetua a confusão operacional, prejudica a confiabilidade da documentação e induz auditorias a erro.

### Opção B: Validação Parcial Baseada em Dicionários
- *Vantagens*: Implementação rápida sem Pydantic.
- *Desvantagens*: Não oferece coerção de tipos, mensagens de erro estruturadas nem prevenção contra injeção de parâmetros inválidos.

### Opção C (Escolhida): Poda Cirúrgica de Chaves Fantasma e Formalização de Schemas Pydantic Estritos com `extra="forbid"`
- *Vantagens*: Elimina 100% dos parâmetros mortos, garante falha rápida contra erros tipográficos e centraliza a validação semântica em schemas formais.
- *Desvantagens*: Qualquer parâmetro residual não documentado fará o boot da aplicação falhar (comportamento desejável para segurança institucional).

---

## 4. Decisão Arquitetural

Adota-se formalmente a **Opção C**. Fica estabelecida a higienização completa do ecossistema de configuração:

### 4.1. Higienização de `config/settings.yaml`
Remover sumariamente de `config/settings.yaml`:
- O bloco `genetic_optimizer` integralmente.
- As chaves `rate_limit.*`, `cache_days`, `brapi_base_url` e `storage.redis_url` da seção `data`.
- A chave `signals.target_pct` da seção `signals`.
- A chave `confirmation_timeout_minutes` da seção `execution`.
- O bloco `broker` contendo parâmetros legados da Cedro não consumidos.

### 4.2. Formalização do Schema Pydantic com `extra="forbid"`
Unificar e estender `RuntimeConfig` (`backend/app/runtime_config.py` e `trading_bot/core/config.py`) com validação Pydantic estrita:

```python
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Literal

class MarketDataConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["yfinance", "cotahist", "mock"] = "yfinance"
    cache_ttl_seconds: int = Field(default=15, ge=1, le=3600)
    history_days: int = Field(default=60, ge=30, le=730)

class SignalsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    donchian_entry_period: int = Field(default=20, ge=5, le=100)
    donchian_exit_period: int = Field(default=10, ge=3, le=50)
    stop_atr_mult: float = Field(default=2.0, ge=0.5, le=5.0)
    target_atr_mult: float = Field(default=3.0, ge=1.0, le=10.0)
    min_volume_threshold: float = Field(default=1_000_000.0, ge=0.0)

class RiskLimitsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_daily_loss_pct: float = Field(default=0.03, gt=0.0, le=0.10)
    max_drawdown_pct: float = Field(default=0.08, gt=0.0, le=0.20)
    max_drawdown_30d_pct: float = Field(default=0.06, gt=0.0, le=0.15)
    max_positions: int = Field(default=5, ge=1, le=20)
    max_position_size_pct: float = Field(default=0.20, gt=0.0, le=0.50)
    kelly_fraction: float = Field(default=0.25, gt=0.0, le=1.0)
    correlation_max: float = Field(default=0.70, gt=0.0, le=1.0)

class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment: Literal["development", "homologation", "production"]
    tickers: List[str] = Field(min_length=1)
    data: MarketDataConfig
    signals: SignalsConfig
    risk: RiskLimitsConfig
    
    @field_validator("tickers")
    @classmethod
    def validate_b3_tickers(cls, v: List[str]) -> List[str]:
        for ticker in v:
            if not ticker.isalnum() or len(ticker) < 4:
                raise ValueError(f"Ticker B3 invalido: {ticker}")
        return v
```

### 4.3. Política de Falha do LLM Formalizada
Consolidar no schema e na lógica de negócio que a política de falha do módulo de LLM é permanentemente imutável como `failure_policy: "hold"`. O sistema recusa qualquer tentativa de configurar *fallback* permissivo até homologação expressa da diretoria executiva.

---

## 5. Consequências

### 5.1. Consequências Positivas
- **Fidelidade Declarativa**: O arquivo `settings.yaml` passa a refletir exatamente o que o motor de trading executa.
- **Detecção Imediata de Erros Humanos**: Se um operador cometer um erro de digitação de parâmetro, a inicialização falhará imediatamente informando o campo exato e a linha correspondente.
- **Limites de Risco Não Burlaríveis**: Valores extremos (como `max_daily_loss_pct: 0.99` ou `kelly_fraction: 5.0`) serão bloqueados na carga do YAML pelo Pydantic antes que qualquer worker inicie.

### 5.2. Consequências Negativas e Mitigações
- **Rigidez Operacional**: Novos parâmetros não podem ser inseridos no YAML sem que o modelo Pydantic seja atualizado em código.
  - *Mitigação*: Este é o comportamento intencional exigido para um sistema institucional de gestão de ativos financeiros.

---

## 6. Governança e Verificação

1. Executar teste automatizado em `tests/test_settings_schema.py` validando que injetar uma chave não mapeada no YAML lança `pydantic.ValidationError`.
2. Verificar que `config/settings.yaml` contém zero parâmetros não consumidos.
3. Testar a rejeição de limites de risco matematicamente inválidos.
