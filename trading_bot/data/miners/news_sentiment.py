"""
Minerador de Dados Nao-Estruturados e Extrator de Sentimento de Noticia
Head of Data Engineering: Orion
Meridian Technologies
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class MarketArticle:
    article_id: str
    title: str
    source: str
    published_at: str
    content: str
    tickers: list[str]


class NewsSentimentMiner:
    """
    Minerador de noticias e comunicados ao mercado.
    Aplica classificacao semantica e pontuacao de sentimento [-1.0 a +1.0]
    com suporte a modelo lexico quantitativo calibrado para o mercado de capitais brasileiro.
    """

    # Lexicon financeiro proprietario calibrado
    POSITIVE_KEYWORDS = {
        "lucro", "recorde", "dividendo", "alta", "salta", "supera", "crescimento",
        "positivo", "alta", "expansao", "geracao de caixa", "upgrade", "recompra",
        "otimismo", "forte", "ganho", "avanco",
    }

    NEGATIVE_KEYWORDS = {
        "prejuizo", "queda", "despenca", "fraude", "greve", "paralisia", "risco",
        "processo", "multa", "rombo", "rebaixamento", "downgrade", "crise",
        "pressao", "perda", "queda brusca", "investigacao",
    }

    def __init__(self, llm_client: Optional[Any] = None):
        self.llm_client = llm_client

    def analyze_text_sentiment(self, text: str) -> float:
        """
        Calcula pontuacao de sentimento entre -1.0 (muito negativo) e +1.0 (muito positivo).
        """
        if not text:
            return 0.0

        lower_text = text.lower()
        pos_count = sum(1 for kw in self.POSITIVE_KEYWORDS if kw in lower_text)
        neg_count = sum(1 for kw in self.NEGATIVE_KEYWORDS if kw in lower_text)

        total = pos_count + neg_count
        if total == 0:
            return 0.0

        # Score normalizado bounded [-1.0, 1.0]
        raw_score = (pos_count - neg_count) / total
        return round(float(raw_score), 3)

    def process_article(self, article: MarketArticle) -> dict[str, Any]:
        """
        Estrutura a noticia em payload higienizado para o Data Lakehouse (Silver Layer).
        """
        score = self.analyze_text_sentiment(f"{article.title} {article.content}")
        article_dict = asdict(article)
        article_dict["sentiment_score"] = score
        article_dict["processed_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        serialized = json.dumps(article_dict, sort_keys=True).encode("utf-8")
        article_dict["sha256"] = hashlib.sha256(serialized).hexdigest()

        return article_dict
