import logging
import random
from typing import List, Dict, Tuple
import pandas as pd
from datetime import date

from trading_bot.signals.engine import compute_signal
from trading_bot.backtest.metrics import calculate_metrics

logger = logging.getLogger(__name__)

class GeneticOptimizer:
    """
    Otimizador de sinais via Algoritmo Genético em Python puro.
    Substitui a busca exaustiva (Grid Search) por evolução, minimizando 
    explosão combinatória.
    """
    def __init__(self, 
                 df_historical: pd.DataFrame, 
                 population_size: int = 10, 
                 mutation_rate: float = 0.15):
        self.df_historical = df_historical
        self.population_size = population_size
        self.mutation_rate = mutation_rate
        
        # Ranges dos parâmetros (genes)
        self.param_bounds = {
            "breakout_period": (10, 40),
            "volume_mult": (1.1, 3.0),
            "rsi_max": (65.0, 85.0),
            "stop_pct": (0.02, 0.10)
        }

    def _generate_individual(self) -> Dict[str, float]:
        """Gera um indivíduo aleatório (cromossomo) dentro dos limites."""
        return {
            "breakout_period": random.randint(self.param_bounds["breakout_period"][0], self.param_bounds["breakout_period"][1]),
            "volume_mult": round(random.uniform(self.param_bounds["volume_mult"][0], self.param_bounds["volume_mult"][1]), 2),
            "rsi_max": round(random.uniform(self.param_bounds["rsi_max"][0], self.param_bounds["rsi_max"][1]), 1),
            "stop_pct": round(random.uniform(self.param_bounds["stop_pct"][0], self.param_bounds["stop_pct"][1]), 3)
        }

    def _fitness(self, individual: dict) -> float:
        """
        Avalia o indivíduo rodando um backtest real com os parâmetros dados.
        Retorna o Sharpe Ratio como métrica de fitness.
        Retorna -1.0 em caso de erro (pior que qualquer resultado válido).
        """
        from trading_bot.backtest.engine import run_regime_backtest
        from trading_bot.backtest.optimizer import calculate_sharpe_ratio

        try:
            # Usa uma janela de 1 ano para fitness (equilíbrio entre velocidade e qualidade)
            from datetime import timedelta
            end = self.df_historical["ts"].max()
            start = end - timedelta(days=365)

            df_window = self.df_historical[
                (self.df_historical["ts"] >= start) &
                (self.df_historical["ts"] <= end)
            ].copy()

            if len(df_window) < 60:  # Sem dados suficientes
                return -1.0

            result = run_regime_backtest(
                data={self.df_historical["ticker"].iloc[0]: df_window},
                regime_name="fitness_eval",
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

    def _tournament_selection(self, population: List[Tuple[Dict, float]], k: int = 3) -> Dict:
        """Seleciona o melhor indivíduo entre 'k' escolhidos aleatoriamente (Torneio)."""
        tournament = random.sample(population, k)
        best = max(tournament, key=lambda item: item[1])
        return best[0].copy()

    def _crossover(self, parent1: Dict, parent2: Dict) -> Dict:
        """Crossover de Ponto Uniforme (Uniform Crossover)."""
        child = {}
        for key in self.param_bounds.keys():
            child[key] = parent1[key] if random.random() > 0.5 else parent2[key]
        return child

    def _mutate(self, individual: Dict) -> Dict:
        """Aplica mutação baseada na taxa configurada."""
        for key, (min_val, max_val) in self.param_bounds.items():
            if random.random() < self.mutation_rate:
                if isinstance(min_val, int):
                    individual[key] = random.randint(min_val, max_val)
                else:
                    individual[key] = round(random.uniform(min_val, max_val), 3)
        return individual

    def evolve(self, generations: int = 5) -> Tuple[Dict, float]:
        """Executa a evolução iterativa."""
        logger.info("Iniciando Otimização Genética: População=%d, Gerações=%d", self.population_size, generations)
        
        # Inicializa população randomica
        population = [self._generate_individual() for _ in range(self.population_size)]
        
        best_overall = None
        best_fitness = -float('inf')

        for gen in range(generations):
            # Fase de Avaliação (Fitness)
            evaluated = []
            for ind in population:
                fit = self._fitness(ind)
                evaluated.append((ind, fit))
                if fit > best_fitness:
                    best_fitness = fit
                    best_overall = ind.copy()
            
            logger.info("Geração %d - Melhor Sharpe local: %.2f", gen, max(f for _, f in evaluated))
            
            # Fase de Reprodução
            new_population = [best_overall.copy()] # Elitismo (preserva o melhor da história)
            while len(new_population) < self.population_size:
                p1 = self._tournament_selection(evaluated)
                p2 = self._tournament_selection(evaluated)
                child = self._crossover(p1, p2)
                child = self._mutate(child)
                new_population.append(child)
                
            population = new_population

        logger.info("Evolução Concluída! Melhor Sharpe global: %.2f | Parâmetros: %s", best_fitness, best_overall)
        return best_overall, best_fitness
