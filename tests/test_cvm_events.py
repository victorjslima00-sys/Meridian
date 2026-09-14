"""
Testes unitarios para o Minerador CVM Dados Abertos — Orion Data Engineering
"""
import pytest
from unittest.mock import patch, MagicMock
from trading_bot.data.miners.cvm_events import CvmEventsMiner


def test_cvm_miner_init():
    miner = CvmEventsMiner()
    assert miner.timeout_sec == 20


def test_parse_proventos_csv():
    miner = CvmEventsMiner()
    # CSV simulando extrato oficial CVM de proventos em dinheiro
    csv_sample = (
        "CNPJ_CIA;DENOM_COMERC;COD_ISIN;TIPO_PROVENTO;DT_APROV;DT_CORTE;DT_PAGTO;VALOR_PROVENTO\n"
        "33.000.167/0001-01;PETROBRAS;BRPETRACNPR6;DIVIDENDO;2025-11-20;2025-12-12;2026-01-15;1.250000\n"
        "33.000.167/0001-01;PETROBRAS;BRPETRACNPR6;JCP;2025-11-20;2025-12-12;2026-01-15;0.650000\n"
        "33.592.510/0001-54;VALE;BRVALEACNOR0;DIVIDENDO;2025-10-15;2025-10-20;2025-11-30;2.300000\n"
    )

    df = miner.parse_proventos_data(csv_sample)
    assert not df.empty
    assert len(df) == 3
    assert "VALOR_PROVENTO" in df.columns
    assert "DT_CORTE" in df.columns

    # Filtrar por ticker/empresa
    petr_df = miner.filter_by_company(df, "PETROBRAS")
    assert len(petr_df) == 2
    assert petr_df["VALOR_PROVENTO"].sum() == pytest.approx(1.90)
