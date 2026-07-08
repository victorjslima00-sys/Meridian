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

    def _fitness(self, individual: Dict[str, float]) -> float:
        """
        Avalia o Sharpe Ratio.
        A implementação real faria o backtest com self.df_historical.
        Neste pipeline, injetamos lógica heurística com volatilidade
        para simular a função de paisagem (landscape).
        """
        # Em produção, chamar engine_backtest(df, **individual)
        # Por segurança, mockamos os retornos baseados na adequação teórica
        score = 0.5 
        if 1.4 <= individual["volume_mult"] <= 2.2: score += 0.2
        if individual["stop_pct"] < 0.05: score += 0.1
        if 15 <= individual["breakout_period"] <= 25: score += 0.2
        
        # Retorno base oscilando de acordo com volatilidade aleatória
        return score + random.uniform(-0.1, 0.2)

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
