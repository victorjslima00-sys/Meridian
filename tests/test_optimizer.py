import pytest
import pandas as pd
import numpy as np
from datetime import date, timedelta
import sys
import types

# Create a real module
ga_module = types.ModuleType('genetic_algorithm')

class FloatGene:
    def __init__(self, min_val=0.0, max_val=1.0, *args, **kwargs):
        self.min_val = min_val
        self.max_val = max_val

class IntGene:
    def __init__(self, min_val=0, max_val=1, *args, **kwargs):
        self.min_val = min_val
        self.max_val = max_val

class GeneticAlgorithm:
    def __init__(self, *args, **kwargs): pass
    def evolve(self): pass

ga_module.FloatGene = FloatGene
ga_module.IntGene = IntGene
ga_module.GeneticAlgorithm = GeneticAlgorithm
sys.modules['genetic_algorithm'] = ga_module

from trading_bot.signals.optimizer import MeridianGeneticOptimizer

def _make_df(n=250, seed=42):
    rng = np.random.default_rng(seed)
    d = date(2023, 1, 2)
    rows = []
    price = 50.0
    n_built = 0
    while n_built < n:
        if d.weekday() < 5:
            price = max(price * (1 + rng.normal(0.0004, 0.012)), 1.0)
            rows.append({"ticker": "TEST3", "ts": d, "o": price, "h": price*1.01,
                         "l": price*0.99, "c": price, "adj_close": price, "v": 500_000})
            n_built += 1
        d += timedelta(days=1)
    return pd.DataFrame(rows)

def test_optimizer_returns_dict_with_valid_params():
    df = _make_df()
    opt = MeridianGeneticOptimizer(df_historical=df)
    result = opt.optimize(population_size=4, generations=2)
    assert isinstance(result, list)
    assert "params" in result[0]
    assert "breakout_period" in result[0]["params"]
    assert 10 <= result[0]["params"]["breakout_period"] <= 50

def test_optimizer_fitness_returns_float():
    df = _make_df()
    opt = MeridianGeneticOptimizer(df_historical=df)
    individual = {"breakout_period": 20, "volume_mult": 2.0, "rsi_max": 70.0, "stop_pct": 0.04}
    score = opt._fitness_function(individual, df)
    assert isinstance(score, float)
    assert score >= -1.0
