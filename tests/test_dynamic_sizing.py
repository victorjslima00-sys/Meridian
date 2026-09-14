"""
Testes unitarios para o Motor Dinamico de Kelly e Multimercado — Atlas Alpha
"""
import pytest
from trading_bot.data.quant.dynamic_sizing import DynamicRegimeKellyEngine


def test_dynamic_kelly_sizing():
    engine = DynamicRegimeKellyEngine(base_fraction=0.25, max_positions=3)
    
    # Regime de Baixa Volatilidade (Oportunidade normal)
    alloc_normal = engine.compute_allocation(
        win_rate=0.55,
        payoff_ratio=2.0,
        volatility_regime="LOW",
        selic_rate=0.139,
    )
    assert alloc_normal["target_allocation_pct"] > 0.0
    assert alloc_normal["per_position_pct"] <= (1.0 / 3.0)

    # Regime de Alta Volatilidade / Pânico (Redução defensiva)
    alloc_panic = engine.compute_allocation(
        win_rate=0.55,
        payoff_ratio=2.0,
        volatility_regime="HIGH",
        selic_rate=0.139,
    )
    # A alocação no pânico deve ser menor que em regime normal
    assert alloc_panic["target_allocation_pct"] < alloc_normal["target_allocation_pct"]
    assert alloc_panic["mode"] == "DEFENSIVE"
