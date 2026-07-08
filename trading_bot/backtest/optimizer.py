import logging
import itertools
from datetime import date
from typing import List, Dict, Any, Tuple
import pandas as pd
import numpy as np

from trading_bot.backtest.engine import run_regime_backtest, BacktestResult
from trading_bot.data.ingestion import fetch_universe_yfinance

logger = logging.getLogger(__name__)

def calculate_sharpe_ratio(equity_curve: List[float], risk_free_rate: float = 0.0) -> float:
    """Calcula o Índice Sharpe Anualizado simplificado."""
    if len(equity_curve) < 2:
        return 0.0
    
    # Converte curva de capital em retornos diários
    returns = pd.Series(equity_curve).pct_change().dropna()
    if returns.empty:
        return 0.0
        
    mean_return = returns.mean()
    std_return = returns.std()
    
    if std_return == 0:
        return 0.0
        
    # Anualiza (assumindo ~252 dias úteis)
    sharpe = (mean_return - risk_free_rate) / std_return * np.sqrt(252)
    return float(sharpe)

def run_grid_search(
    data: Dict[str, pd.DataFrame],
    param_grid: Dict[str, List[Any]],
    start_date: date,
    end_date: date,
    capital: float = 10000.0
) -> List[Dict[str, Any]]:
    """
    Roda a força bruta (Grid Search) testando todas as combinações do param_grid.
    Retorna uma lista de resultados ordenados pelo melhor Índice Sharpe.
    """
    keys, values = zip(*param_grid.items())
    permutations = [dict(zip(keys, v)) for v in itertools.product(*values)]
    
    logger.info(f"Iniciando Grid Search com {len(permutations)} combinações...")
    
    results = []
    
    for i, params in enumerate(permutations):
        logger.info(f"Testando combinação {i+1}/{len(permutations)}: {params}")
        
        # Roda um backtest único pegando todo o período
        res = run_regime_backtest(
            data=data,
            regime_name=f"Opt_{i}",
            start=start_date,
            end=end_date,
            capital=capital,
            signal_params=params,
            ibov_filter=True # Mantém o filtro macro ligado
        )
        
        sharpe = calculate_sharpe_ratio(res.equity_curve)
        win_rate = 0.0
        if res.closed_trades:
            wins = [t for t in res.closed_trades if t.pnl_abs > 0]
            win_rate = len(wins) / len(res.closed_trades)
            
        return_pct = (res.final_capital / res.initial_capital - 1) * 100
        
        results.append({
            "params": params,
            "sharpe": sharpe,
            "return_pct": return_pct,
            "win_rate": win_rate,
            "trades_count": len(res.trades)
        })
        
    # Ordena pelo maior Sharpe Ratio
    results.sort(key=lambda x: x["sharpe"], reverse=True)
    return results
