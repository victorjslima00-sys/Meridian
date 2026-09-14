"""
Testes unitarios para o Conciliador de Proventos CVM vs Precos XP
"""
import pytest
from trading_bot.data.quant.actions_conciliator import CorporateActionsConciliator


def test_conciliate_petr4_divergence():
    conciliator = CorporateActionsConciliator()
    # Em 12/12/2025: Nominal = 39.26, Ajustado XP = 36.10, Delta = 3.16
    # Proventos pagos: 1.15 + 0.51 + 0.85 + 0.65 = 3.16
    nominal = 39.26
    adjusted = 36.10
    dividends = [1.15, 0.51, 0.85, 0.65]

    res = conciliator.conciliate_divergence(nominal, adjusted, dividends)
    assert res["observed_delta"] == 3.16
    assert res["total_dividends_cvm"] == 3.16
    assert res["residual"] == 0.0
    assert res["is_fully_explained"] is True
