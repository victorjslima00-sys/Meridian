"""
Testes unitarios para o Sanitizador e Lakehouse Storage Manager — Orion Data Engineering
"""
import json
import os
import pandas as pd
import pytest
from trading_bot.data.lakehouse.storage_manager import LakehouseStorageManager


def test_lakehouse_ingest_bronze_and_promote_silver(tmp_path):
    lakehouse = LakehouseStorageManager(base_dir=str(tmp_path / "lakehouse"))

    # 1. Ingestao Camada Bronze (Dado Bruto Imutavel)
    raw_payload = {
        "source": "cvm_fatos_relevantes",
        "ticker": "PETR4",
        "headline": "Aprovacao de Dividendos Extraordinarios",
        "body": "Conselho aprova pagamento de R$ 1.20 por acao.",
        "published_at": "2026-09-12T18:00:00Z",
    }
    bronze_meta = lakehouse.save_bronze(
        dataset_name="cvm_news",
        record_id="20260912_petr4_001",
        payload=raw_payload,
    )

    assert os.path.exists(bronze_meta["file_path"])
    assert bronze_meta["sha256"] is not None
    assert len(bronze_meta["sha256"]) == 64

    # 2. Promocao para Camada Silver (Dado Sanitizado & Estruturado)
    clean_df = pd.DataFrame([{
        "ticker": "PETR4",
        "event_type": "DIVIDEND_ANNOUNCEMENT",
        "estimated_value": 1.20,
        "sentiment_score": 0.85,
        "reference_date": "2026-09-12",
    }])

    silver_meta = lakehouse.save_silver(
        dataset_name="corporate_events_clean",
        df=clean_df,
    )

    assert os.path.exists(silver_meta["file_path"])
    assert silver_meta["sha256"] is not None
    assert silver_meta["row_count"] == 1


def test_lakehouse_manifest_integrity(tmp_path):
    lakehouse = LakehouseStorageManager(base_dir=str(tmp_path / "lakehouse"))
    lakehouse.save_bronze("test_ds", "rec_1", {"foo": "bar"})

    manifest = lakehouse.generate_integrity_manifest()
    assert "timestamp_utc" in manifest
    assert "bronze_count" in manifest
    assert manifest["bronze_count"] == 1
