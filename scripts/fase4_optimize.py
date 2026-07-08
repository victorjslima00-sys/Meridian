#!/usr/bin/env python3
import sys
import logging
from datetime import date
from pprint import pprint

from trading_bot.core.config import AppConfig, setup_logging
from trading_bot.data.ingestion import fetch_universe_yfinance
from trading_bot.backtest.optimizer import run_grid_search

def main():
    print("🚀 Iniciando Motor de Otimização Quântica (Grid Search)")
    cfg = AppConfig.load()
    setup_logging(cfg)
    logger = logging.getLogger("Optimizer")
    
    # Busca ativos do universo configurado
    tickers = cfg.get("_universe", "tickers", default=[])
    if not tickers:
        print("Universo vazio.")
        sys.exit(1)
        
    print(f"Baixando histórico de {len(tickers)} ativos para o laboratório...")
    start_date = date(2021, 1, 1) # Vamos testar os ultimos 3-4 anos
    end_date = date.today()
    
    data = fetch_universe_yfinance(tickers, start=start_date)
    
    # -------------------------------------------------------------
    # GRID DE PARÂMETROS
    # -------------------------------------------------------------
    # Se testarmos muitas variações, o tempo cresce exponencialmente.
    # Vamos fazer um Grid 2x3x2x3 = 36 simulações completas do mercado.
    param_grid = {
        "breakout_period": [15, 20],
        "rsi_max": [70, 75, 80],
        "stop_pct": [0.03, 0.05],
        "target_pct": [0.08, 0.10, 0.15]
    }
    
    results = run_grid_search(
        data=data,
        param_grid=param_grid,
        start_date=start_date,
        end_date=end_date,
        capital=cfg.get("risk", "capital_initial", default=300.0)
    )
    
    print("\n🏆 RESULTADOS DA OTIMIZAÇÃO 🏆")
    print("=================================")
    # Pega o Top 3
    for i, res in enumerate(results[:3]):
        print(f"\n#{i+1} Melhor Configuração:")
        pprint(res["params"])
        print(f"Sharpe Ratio: {res['sharpe']:.2f}")
        print(f"Retorno Total: {res['return_pct']:.2f}%")
        print(f"Win Rate: {res['win_rate']*100:.1f}%")
        print(f"Trades Executados: {res['trades_count']}")

if __name__ == "__main__":
    main()
