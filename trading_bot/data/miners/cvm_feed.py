"""
Agregador de Fatos Relevantes e Comunicados em Tempo Real — CVM
Head of Data Engineering: Orion
Meridian Technologies
"""
from __future__ import annotations

import datetime
import json
import logging
from typing import Any, List, Optional

from trading_bot.data.lakehouse.storage_manager import LakehouseStorageManager

logger = logging.getLogger(__name__)


class CvmFeedAggregator:
    """
    Agrega e filtra eventos societarios oficiais (Fatos Relevantes, Avisos aos Acionistas)
    para o universo de cobertura de ativos operados pelo Meridian.
    """

    def __init__(self, tickers: List[str], storage: Optional[LakehouseStorageManager] = None):
        self.tickers = set(t.upper() for t in tickers)
        self.storage = storage or LakehouseStorageManager()

    def filter_relevant_events(self, events: List[dict[str, Any]]) -> List[dict[str, Any]]:
        """
        Filtra apenas comunicados pertencentes aos ativos monitorados.
        """
        filtered = []
        for ev in events:
            ev_ticker = str(ev.get("ticker", "")).upper()
            if ev_ticker in self.tickers:
                filtered.append(ev)
        return filtered

    def ingest_events_batch(
        self,
        raw_events: List[dict[str, Any]],
        batch_id: str,
        source_url: Optional[str] = None,
    ) -> tuple[List[dict[str, Any]], dict[str, Any]]:
        """
        Persiste o lote bruto de comunicados recebidos da CVM na camada Bronze
        com calculo de hash SHA-256 e manifesto, antes de aplicar o filtro de ativos.
        """
        if not isinstance(raw_events, list):
            raise TypeError("raw_events_must_be_list")
        payload_bytes = json.dumps(raw_events, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        meta = self.storage.save_bronze_raw(
            dataset_name="cvm_news",
            record_id=batch_id,
            raw_bytes=payload_bytes,
            extension="json",
            metadata={
                "source_url": source_url or "https://dados.cvm.gov.br/feed/fatos_relevantes",
                "retrieved_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "event_count": len(raw_events),
                "validation_status": "accepted",
            },
        )
        filtered = self.filter_relevant_events(raw_events)
        return filtered, meta
