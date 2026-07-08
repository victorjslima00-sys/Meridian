<div align="center">
  <img src="assets/meridian_banner.jpg" alt="Meridian Banner" width="100%">
  
  <h1>🌌 Meridian Trading Bot</h1>
  <p><strong>Inteligência Quantitativa Autônoma para a B3</strong></p>

  <p>
    <img src="https://img.shields.io/badge/Status-Fase%206%20(Comit%C3%AA%20Multi--Agentes)-success" alt="Status">
    <img src="https://img.shields.io/badge/Mercado-B3%20(A%C3%A7%C3%B5es)-blue" alt="Mercado">
    <img src="https://img.shields.io/badge/Stack-Python%20%7C%20AWS%20%7C%20SQLite-lightgrey" alt="Stack">
    <img src="https://img.shields.io/badge/Modo-100%25%20Aut%C3%B4nomo-blueviolet" alt="Autonomia">
  </p>
</div>

---

## ⚡ Instalação Rápida

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
- Tolerância de até 2 grandes movimentos não ajustados (eventos corporativos legítimos)
- Validação cruzada de dados de fechamento usando bases com/sem ajustes do yfinance (devido à falta de histórico diário gratuito no brapi)

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
| **0** | ✅ Concluída | Validação de dados (yfinance / brapi) |
| **1** | ✅ Concluída | Motor de sinais + backtesting |
| **2** | ✅ Concluída | Risco + circuit breaker + correlações |
| **3** | ✅ Concluída | Cloud Enterprise (Terraform + AWS + GitHub Actions CI/CD) |
| **4** | ✅ Concluída | Otimização Quântica (Motor de Grid Search) |
| **5** | ✅ Concluída | Automação Total (100% Autônomo) |
| **6** | ✅ Concluída | Comitê Multi-Agentes de IA (Pesquisador + Guard-Rail) |
| **7** | ⏳ Pendente | Painel Web (Frontend separado do Backend) |

## Qualidade e Cobertura de Código

O repositório possui Integração Contínua (CI) configurada com:
- **GitHub Actions**: Deploy automatizado via SSH para EC2.
- **Segurança Infra**: Fail2Ban, Logrotate e UFW no servidor Ubuntu.
- **Flake8**: Validação rigorosa de estilo e qualidade.
- **Pytest + Coverage**: Testes abrangentes para ingestão e validação.

## Notas de Segurança (Arquitetura Atual)

- **Comitê de IA Ativo**: Agente Guard-Rail avalia e barra qualquer otimização ou trade baseado em Fake News ou alucinação algorítmica. Triangulação obrigatória em fontes Tier-1.
- **Autonomia Total**: O bot foi destravado da dependência humana. Confirmação manual de ordens via Telegram foi **revogada**.
- **Stop-loss Nativo**: Ordem STOP disparada e gerenciada no momento da entrada.
- **Circuit Breaker**: Implementado com 3 limites simultâneos (diário, inception, rolling 30d).
