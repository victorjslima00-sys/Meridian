"""
Testes unitarios para o Agregador CVM de Fatos Relevantes — Orion Data Engineering
"""
import pytest
from trading_bot.data.miners.cvm_feed import CvmFeedAggregator


def test_cvm_feed_aggregator_init():
    agg = CvmFeedAggregator(tickers=["PETR4", "VALE3"])
    assert "PETR4" in agg.tickers
    assert "VALE3" in agg.tickers


def test_cvm_mock_feed_processing():
    agg = CvmFeedAggregator(tickers=["PETR4", "VALE3"])
    mock_events = [
        {"ticker": "PETR4", "tipo": "FATO_RELEVANTE", "titulo": "Descoberta de novos campos no Pre-Sal", "data": "12/09/2026"},
        {"ticker": "VALE3", "tipo": "AVISO_ACIONISTAS", "titulo": "Aprovacao de proventos em dinheiro", "data": "11/09/2026"},
        {"ticker": "BBAS3", "tipo": "COMUNICADO", "titulo": "Outro evento", "data": "10/09/2026"},
    ]
    
    filtered = agg.filter_relevant_events(mock_events)
    assert len(filtered) == 2
    assert filtered[0]["ticker"] == "PETR4"
    assert filtered[1]["ticker"] == "VALE3"
