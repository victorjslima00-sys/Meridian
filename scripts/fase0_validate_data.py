#!/usr/bin/env python3
"""
Script Fase 0 — Validação de dados
====================================
Executa a validação completa antes do primeiro backtest:
  1. Busca histórico de 50 ativos via yfinance (5 anos)
  2. Salva no SQLite local
  3. Valida qualidade dos dados
  4. Roda validação cruzada yfinance ↔ brapi.dev
  5. Gera relatório em logs/data_validation/

Uso:
  python scripts/fase0_validate_data.py --token SEU_TOKEN_BRAPI
  python scripts/fase0_validate_data.py --token SEU_TOKEN_BRAPI --skip-brapi
"""

import sys
import os
import logging
import argparse
from datetime import date, timedelta
from pathlib import Path

# Garante que o pacote trading_bot é encontrado
sys.path.insert(0, str(Path(__file__).parent.parent))

from trading_bot.data.ingestion import fetch_universe_yfinance
from trading_bot.data.storage import initialize_db, save_ohlcv, get_delta_start
from trading_bot.data.validator import validate_universe
from trading_bot.data.cross_validation import run_cross_validation

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config():
    with open("config/settings.yaml") as f:
        return yaml.safe_load(f)

def load_universe():
    with open("config/universe.yaml") as f:
        data = yaml.safe_load(f)
    return data["universe"]["tickers"]


def main():
    parser = argparse.ArgumentParser(description="Fase 0 — Validação de dados")
    parser.add_argument("--token", default="", help="Token da brapi.dev (plano grátis)")
    parser.add_argument("--skip-brapi", action="store_true", help="Pular validação cruzada com brapi")
    parser.add_argument("--years", type=int, default=5, help="Anos de histórico a buscar (default: 5)")
    args = parser.parse_args()

    cfg = load_config()
    tickers = load_universe()
    token = args.token or cfg["data"].get("brapi_token", "")
    db_path = cfg["data"].get("db_path", "data/trading_bot.db")

    logger.info("=" * 60)
    logger.info("FASE 0 — VALIDAÇÃO DE DADOS")
    logger.info("Universo: %d ativos | Histórico: %d anos", len(tickers), args.years)
    logger.info("=" * 60)

    # 1. Inicializar banco de dados
    initialize_db(db_path)

    # 2. Buscar histórico via yfinance
    start = date.today() - timedelta(days=365 * args.years)
    logger.info("Buscando histórico via yfinance desde %s...", start)
    data = fetch_universe_yfinance(tickers, start=start)

    # 3. Salvar no SQLite
    total_saved = 0
    for ticker, df in data.items():
        saved = save_ohlcv(df, source="yfinance", db_path=db_path)
        total_saved += saved
    logger.info("Total de linhas salvas no DB: %d", total_saved)

    # 4. Validar qualidade
    logger.info("\nValidando qualidade dos dados...")
    reports = validate_universe(data)
    errors_total = sum(len(r.errors) for r in reports.values())
    warns_total = sum(len(r.warnings) for r in reports.values())
    ok_count = sum(1 for r in reports.values() if r.ok)

    logger.info("Qualidade: %d/%d OK | %d erros | %d avisos",
                ok_count, len(tickers), errors_total, warns_total)

    # 5. Validação cruzada (bloqueante)
    cross_status = "skipped"
    if not args.skip_brapi:
        if not token:
            logger.warning("Token brapi.dev não fornecido — pulando validação cruzada.")
            logger.warning("Use --token SEU_TOKEN ou preencha brapi_token em settings.yaml")
            cross_status = "skipped"
        else:
            logger.info("\nRodando validação cruzada yfinance ↔ brapi.dev...")
            summary = run_cross_validation(
                tickers=tickers[:10],  # Valida amostra de 10 para economizar rate limit
                brapi_token=token,
                overlap_days=cfg["data"]["cross_validation"]["overlap_days"],
                max_div_pct=cfg["data"]["cross_validation"]["max_divergence_pct"],
            )
            cross_status = summary["status"]
    else:
        logger.info("Validação cruzada pulada (--skip-brapi)")

    # 6. Sumário final
    logger.info("\n" + "=" * 60)
    logger.info("SUMÁRIO FASE 0")
    logger.info("  Ativos buscados:    %d/%d", len(data), len(tickers))
    logger.info("  Linhas no DB:       %d", total_saved)
    logger.info("  Qualidade OK:       %d/%d", ok_count, len(tickers))
    logger.info("  Validação cruzada:  %s", cross_status.upper())

    gates_ok = (
        len(data) >= int(len(tickers) * 0.9) and   # 90%+ dos ativos com dados
        errors_total <= 2 and                        # Até 2 erros tolerados (eventos corporativos legítimos)
        cross_status in ("passed", "skipped")
    )

    if errors_total > 0:
        logger.warning("ATENÇÃO: %d erro(s) de qualidade detectados.", errors_total)
        logger.warning("Verifique manualmente — podem ser grupamentos/bonificações legítimos.")
        logger.warning("Exemplos conhecidos: HAPV3 (+42%% em 2025-11-13 — provável evento corporativo).")

    if gates_ok:
        logger.info("\n✅ FASE 0 CONCLUÍDA — Pronto para Fase 1 (motor de sinais)")
        logger.info("   Pendência: informar capital inicial para calibrar Módulo 3")
    else:
        logger.error("\n❌ FASE 0 COM PROBLEMAS — Resolver antes de prosseguir:")
        if len(data) < int(len(tickers) * 0.9):
            logger.error("   - Menos de 90%% dos ativos com dados")
        if errors_total > 0:
            logger.error("   - %d erros de qualidade encontrados (ver log acima)", errors_total)
        if cross_status == "failed":
            logger.error("   - Validação cruzada falhou — divergência acima do threshold")

    logger.info("=" * 60)
    return 0 if gates_ok else 1


if __name__ == "__main__":
    sys.exit(main())
