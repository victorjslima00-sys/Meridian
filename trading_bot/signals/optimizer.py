import logging
import random
import pandas as pd
from typing import Dict, List, Tuple
from genetic_algorithm.GeneticAlgorithm import GeneticAlgorithm
from genetic_algorithm.IntGene import IntGene
from genetic_algorithm.FloatGene import FloatGene

logger = logging.getLogger(__name__)

# Sistema de registro plugável exigido pelo usuário
_FITNESS_REGISTRY = {}

def register_fitness(name: str):
    def decorator(func):
        _FITNESS_REGISTRY[name] = func
        return func
    return decorator

class MeridianGeneticOptimizer:
    """
    Otimizador evolutivo reescrito para utilizar a biblioteca 'genetic-algorithm'.
    """
    def __init__(self, df_historical: pd.DataFrame, param_bounds: dict = None):
        self.df_historical = df_historical
        
        # Converte as bounds do settings para os Genes da biblioteca
        bounds = param_bounds or {
            "breakout_period": (10, 50),
            "volume_mult": (1.0, 3.0),
            "rsi_max": (65.0, 85.0),
            "stop_pct": (0.02, 0.10)
        }
        
        self.param_space = {
            "breakout_period": IntGene(bounds["breakout_period"][0], bounds["breakout_period"][1]),
            "volume_mult": FloatGene(bounds["volume_mult"][0], bounds["volume_mult"][1]),
            "rsi_max": FloatGene(bounds["rsi_max"][0], bounds["rsi_max"][1]),
            "stop_pct": FloatGene(bounds["stop_pct"][0], bounds["stop_pct"][1])
        }

    @staticmethod
    @register_fitness("sharpe_backtest")
    def _fitness_function(individual: dict, df_historical: pd.DataFrame) -> float:
        """
        Função de fitness real que roda o backtest e devolve o Sharpe.
        """
        from trading_bot.backtest.engine import run_regime_backtest
        from trading_bot.backtest.optimizer import calculate_sharpe_ratio
        
        try:
            from datetime import timedelta
            end = df_historical["ts"].max()
            start = end - timedelta(days=365)
            df_window = df_historical[
                (df_historical["ts"] >= start) & (df_historical["ts"] <= end)
            ].copy()

            if len(df_window) < 60:
                return -1.0

            result = run_regime_backtest(
                data={df_historical["ticker"].iloc[0]: df_window},
                regime_name="fitness",
                start=start,
                end=end,
                capital=1000.0,
                ibov_filter=False,
                signal_params={
                    "breakout_period": int(individual["breakout_period"]),
                    "volume_mult": float(individual["volume_mult"]),
                    "rsi_max": float(individual["rsi_max"]),
                    "stop_pct": float(individual["stop_pct"]),
                },
            )

            if len(result.equity_curve) < 10:
                return 0.0

            return calculate_sharpe_ratio(result.equity_curve)

        except Exception as e:
            logger.warning("Erro no fitness do genético: %s", e)
            return -1.0

    def optimize(self, population_size: int = 20, generations: int = 10) -> List[Dict]:
        """
        Executa a otimização genética delegando à biblioteca.
        """
        logger.info("Iniciando Otimização Genética com %d indivíduos por %d gerações.", population_size, generations)
        
        fitness_func = _FITNESS_REGISTRY["sharpe_backtest"]
        
        # A biblioteca espera um 'model' que pode ser chamado com os parâmetros
        def model_wrapper(params):
            return fitness_func(params, self.df_historical)
            
        ga = GeneticAlgorithm(
            model=model_wrapper,
            param_space=self.param_space,
            pop_size=population_size,
            max_iter=generations,
            verbose=False
        )
        
        try:
            result = ga.evolve()  # ← captura o retorno!
            best_params = result.get("best params", {})
            best_sharpe = result.get("best fitness", 0.0)
            logger.info("Evolução concluída. Melhor Sharpe: %.4f | Params: %s",
                        best_sharpe, best_params)
        except Exception as e:
            logger.warning("Erro na evolução genética: %s. Usando params padrão.", e)
            # Fallback seguro: parâmetros do meio dos bounds
            best_params = {}
            for k, v in self.param_space.items():
                if hasattr(v, "min_val") and hasattr(v, "max_val"):
                    if isinstance(v, float) or "Float" in str(type(v)):
                        best_params[k] = (v.min_val + v.max_val) / 2
                    else:
                        best_params[k] = int((v.min_val + v.max_val) / 2)
                else:
                    best_params[k] = 20 # Ultimate fallback
            best_sharpe = 0.0

        return [{
            "params": best_params,
            "sharpe": best_sharpe,        # ← valor real, não hardcoded 1.5
            "return_pct": None,           # calculado externamente se necessário
            "win_rate": None,
            "trades_count": None,
        }]
