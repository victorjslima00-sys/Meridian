<div align="center">
  <img src="assets/meridian_banner.jpg" alt="Meridian" width="100%">
  
  <h1>Meridian Trading System</h1>
  <p><strong>Inteligência Quantitativa Autônoma para a B3</strong></p>

  <p>
    <img src="https://img.shields.io/badge/Status-Fase%206-success" alt="Status">
    <img src="https://img.shields.io/badge/Market-B3-blue" alt="Mercado">
    <img src="https://img.shields.io/badge/Stack-Python%20%7C%20AWS%20%7C%20SQLite-lightgrey" alt="Stack">
    <img src="https://img.shields.io/badge/Execution-100%25%20Autonomous-blueviolet" alt="Autonomia">
  </p>
</div>

---

## Instalação Rápida

```bash
cd trading-bot
pip install -r requirements.txt
```

## Configuração

1. Edite `config/settings.yaml` e preencha:
   - `data.brapi_token` — token da brapi.dev (plano grátis)
   - `notifications.telegram_bot_token` e `telegram_chat_id`

2. Revise `config/universe.yaml` — 50 ativos pré-configurados do IBOVESPA

## Executar Validação de Dados

```bash
# Com token brapi.dev (recomendado)
python scripts/fase0_validate_data.py --token SEU_TOKEN_BRAPI

# Sem token (pula validação cruzada)
python scripts/fase0_validate_data.py --skip-brapi
```

## Fases de Implementação

| Fase | Status | Descrição |
|------|--------|-----------|
| **0** | Concluída | Validação de dados (yfinance / brapi) |
| **1** | Concluída | Motor de sinais + backtesting |
| **2** | Concluída | Risco + circuit breaker + correlações |
| **3** | Concluída | Cloud Enterprise (Terraform + AWS + CI/CD) |
| **4** | Concluída | Otimização Quântica (Motor de Grid Search) |
| **5** | Concluída | Automação Total (100% Autônomo) |
| **6** | Concluída | Comitê Multi-Agentes de IA (Supervisão) |
| **7** | Pendente | Painel Web (Frontend separado do Backend) |

## Qualidade e Cobertura de Código

O repositório possui Integração Contínua (CI) configurada com:
- **GitHub Actions**: Deploy automatizado via SSH para EC2.
- **Segurança Infra**: Fail2Ban, Logrotate e UFW no servidor Ubuntu.
- **Flake8**: Validação rigorosa de estilo e qualidade.
- **Pytest + Coverage**: Testes abrangentes para ingestão e validação.

## Notas de Segurança (Arquitetura Atual)

- **Aviso Legal:** A integração com a corretora (Cedro) no momento atua estritamente em **Paper Trading** (simulação local). Nenhuma ordem real é executada em produção até configuração futura explícita.

- **Comitê de IA Ativo**: Agente Guard-Rail avalia e barra qualquer otimização ou trade baseado em Fake News ou alucinação algorítmica. Triangulação obrigatória em fontes Tier-1.
- **Autonomia Total**: O bot foi destravado da dependência humana. Confirmação manual de ordens via Telegram foi **revogada**.
- **Stop-loss Nativo**: Ordem STOP disparada e gerenciada no momento da entrada.
- **Circuit Breaker**: Implementado com 3 limites simultâneos (diário, inception, rolling 30d).
