# Meridian

> **Status**: Em desenvolvimento — Fase 0 (validação de dados)  
> **Mercado**: B3 (ações brasileiras) | **Timeframe**: Candle diário  
> **Stack**: Python 3.11+ · SQLite · brapi.dev · yfinance · Cedro Technologies

---

## Instalação

```bash
cd trading-bot
pip install -r requirements.txt
```

## Configuração

1. Edite `config/settings.yaml` e preencha:
   - `data.brapi_token` — token da [brapi.dev](https://brapi.dev) (plano grátis)
   - `notifications.telegram_bot_token` e `telegram_chat_id`
   - `broker.api_key` / `api_secret` (Cedro Technologies — após contato comercial)

2. Revise `config/universe.yaml` — 50 ativos pré-configurados do IBOVESPA

> **⚠️ Pendente**: informar capital inicial para calibrar o Módulo 3 (Kelly fracionado)

## Executar Fase 0 — Validação de Dados

```bash
# Com token brapi.dev (recomendado)
python scripts/fase0_validate_data.py --token SEU_TOKEN_BRAPI

# Sem token (pula validação cruzada)
python scripts/fase0_validate_data.py --skip-brapi

# Histórico menor (mais rápido para testes)
python scripts/fase0_validate_data.py --token SEU_TOKEN_BRAPI --years 2
```

**Gate de saída da Fase 0:**
- ≥90% dos ativos com dados históricos
- Zero erros de qualidade (gaps, splits não ajustados)
- Validação cruzada yfinance ↔ brapi.dev com divergência < 0.5%

## Estrutura de Pastas

```
trading-bot/
├── config/
│   ├── settings.yaml        # Configurações do sistema
│   └── universe.yaml        # 50 ativos monitorados
├── trading_bot/
│   ├── data/                # Módulo 1: ingestão, storage, validação
│   ├── signals/             # Módulo 2: motor de sinais
│   ├── backtest/            # Módulo 2: backtesting e métricas
│   ├── risk/                # Módulo 3: gestão de risco + circuit breaker
│   ├── execution/           # Módulo 4: modo manual/auto
│   ├── broker/              # Módulo 5: integração Cedro Technologies
│   ├── agents/              # Módulo 6: agentes de IA (pesquisa + alocação)
│   ├── dashboard/           # Módulo 7: dashboard web
│   └── core/                # Módulo 8: logger, notificações, scheduler
├── scripts/
│   └── fase0_validate_data.py
├── tests/
├── logs/
│   └── data_validation/     # Relatórios de validação cruzada
└── data/
    └── trading_bot.db       # SQLite (gerado automaticamente)
```

## Fases de Implementação

| Fase | Status | Descrição |
|------|--------|-----------|
| **0** | 🔄 Em andamento | Validação de dados |
| **1** | ⏳ Pendente | Motor de sinais + backtesting |
| **2** | ⏳ Pendente | Risco + circuit breaker + notificações |
| **3** | ⏳ Pendente | Dashboard web |
| **4a** | ⏳ Pendente | PoC corretora (Cedro) |
| **4b** | ⏳ Pendente | Paper trading (1-2 semanas) |
| **5** | ⏳ Pendente | Live trading — modo manual |
| **6** | ⏳ Pendente | Agentes de IA |
| **7** | ⏳ Pendente | Automação total (decisão deliberada) |

## Notas de Segurança

- **Stop-loss**: implementado como ordem STOP nativa na corretora (não depende do sistema estar rodando)
- **Confirmação manual**: padrão inicial — todas as ordens exigem aprovação via Telegram
- **Timeout**: sinais expiram sem aprovação → **REJEIÇÃO automática** (nunca auto-aprovação)
- **Paper trading obrigatório**: 1-2 semanas com ordens simuladas antes de qualquer capital real
- **Circuit breaker**: 3 limites simultâneos (diário -3%, inception -8%, rolling 30d -6%)
