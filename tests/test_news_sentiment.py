"""
Testes unitarios para o Minador de Noticias e LLM Sentiment Extractor
"""
import pytest
from unittest.mock import MagicMock
from trading_bot.data.miners.news_sentiment import NewsSentimentMiner, MarketArticle


def test_market_article_dataclass():
    art = MarketArticle(
        article_id="art_001",
        title="Petrobras bate recorde de producao no pre-sal",
        source="Valor / CVM",
        published_at="2026-09-12T10:00:00Z",
        content="A Petrobras informou producao historica no terceiro trimestre...",
        tickers=["PETR4"],
    )
    assert art.article_id == "art_001"
    assert "PETR4" in art.tickers


def test_sentiment_scoring_deterministic():
    miner = NewsSentimentMiner()
    
    # Texto nitidamente positivo
    score_pos = miner.analyze_text_sentiment("Lucro liquido da Petrobras salta 45% com forte geracao de caixa e dividendos recordes")
    assert score_pos > 0.3
    
    # Texto nitidamente negativo
    score_neg = miner.analyze_text_sentiment("Petrobras sofre queda brusca na receita e enfrenta greve com risco de paralise operacional")
    assert score_neg < -0.2
