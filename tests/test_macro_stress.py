"""
Testes unitarios para o Simulador de Estresse Macro & Monte Carlo — Orion Quant
"""
import numpy as np
import pytest
from trading_bot.data.quant.macro_stress import MacroStressSimulator


def test_stress_simulator_initialization():
    sim = MacroStressSimulator(initial_selic=13.9, n_simulations=500)
    assert sim.initial_selic == 13.9
    assert sim.n_simulations == 500


def test_stress_scenarios_generation():
    sim = MacroStressSimulator(initial_selic=13.9, n_simulations=1000)
    scenarios = sim.simulate_selic_shocks(shocks_bps=[-200, -100, 0, 100, 200])
    
    assert len(scenarios) == 5
    assert scenarios[0]["shock_bps"] == -200
    assert scenarios[0]["simulated_selic"] == pytest.approx(11.9)
    assert scenarios[4]["shock_bps"] == 200
    assert scenarios[4]["simulated_selic"] == pytest.approx(15.9)
    
    # Valida projecao de custo de oportunidade contra o benchmark
    for sc in scenarios:
        assert "expected_hurdle_rate" in sc
        assert "risk_appetite_multiplier" in sc
        # Se os juros sobem, o apetite por risco/tamanho da posicao deve cair
        if sc["shock_bps"] > 0:
            assert sc["risk_appetite_multiplier"] < 1.0
        elif sc["shock_bps"] < 0:
            assert sc["risk_appetite_multiplier"] > 1.0
