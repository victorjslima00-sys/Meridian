"""
Testes de persistência de bytes brutos Bacen e CVM no Lakehouse local — Orion Data Engineering
Validação estrita de imutabilidade, inventário SHA-256 e preservação de reprovações para auditoria.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from trading_bot.data.lakehouse.storage_manager import LakehouseStorageManager
from trading_bot.data.miners.bacen_sgs import BacenSgsMiner
from trading_bot.data.miners.cvm_events import CvmEventsMiner
from trading_bot.data.miners.cvm_feed import CvmFeedAggregator


def test_save_bronze_raw_exclusive_write_and_manifest(tmp_path):
    storage = LakehouseStorageManager(base_dir=str(tmp_path / "lake"))
    raw_payload = b"col1;col2\nval1;val2\n"
    meta = storage.save_bronze_raw(
        dataset_name="custom_raw",
        record_id="rec_001",
        raw_bytes=raw_payload,
        extension="csv",
        metadata={"source": "test_provider", "custom_flag": True},
    )

    payload_path = Path(meta["file_path"])
    manifest_path = payload_path.with_name("rec_001.manifest.json")

    assert payload_path.is_file()
    assert manifest_path.is_file()
    assert payload_path.read_bytes() == raw_payload

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["sha256"] == hashlib.sha256(raw_payload).hexdigest()
    assert manifest_data["size_bytes"] == len(raw_payload)
    assert manifest_data["layer"] == "bronze"
    assert manifest_data["dataset"] == "custom_raw"
    assert manifest_data["record_id"] == "rec_001"
    assert manifest_data["custom_flag"] is True

    # Escrita exclusiva ('xb'): duplicata levanta FileExistsError sem sobrescrever
    with pytest.raises(FileExistsError):
        storage.save_bronze_raw(
            dataset_name="custom_raw",
            record_id="rec_001",
            raw_bytes=b"mutated",
            extension="csv",
        )
    assert payload_path.read_bytes() == raw_payload


def test_read_bronze_raw_verifies_hash_and_detects_tampering(tmp_path):
    storage = LakehouseStorageManager(base_dir=str(tmp_path / "lake"))
    raw_payload = b'{"status": "ok", "series": [1, 2, 3]}'
    meta = storage.save_bronze_raw(
        dataset_name="series_json",
        record_id="batch_01",
        raw_bytes=raw_payload,
        extension="json",
    )

    # Leitura bem-sucedida com hash idêntico
    data_bytes, manifest = storage.read_bronze("series_json", "batch_01", extension="json")
    assert data_bytes == raw_payload
    assert manifest["sha256"] == hashlib.sha256(raw_payload).hexdigest()

    # Adulteração maliciosa do arquivo no disco
    payload_file = Path(meta["file_path"])
    payload_file.write_bytes(b'{"status": "tampered"}')

    with pytest.raises(ValueError, match="hash_mismatch"):
        storage.read_bronze("series_json", "batch_01", extension="json")


def test_bacen_sgs_persists_raw_bytes_to_lakehouse(tmp_path):
    storage = LakehouseStorageManager(base_dir=str(tmp_path / "lake"))
    miner = BacenSgsMiner(storage=storage)

    mock_json = [
        {"data": "10/09/2026", "valor": "0.0452"},
        {"data": "11/09/2026", "valor": "0.0453"},
    ]
    raw_bytes = json.dumps(mock_json).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw_bytes

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        df = miner.fetch_series(series_code=11, last_n=2)

    assert not df.empty
    assert len(df) == 2

    raw_path = Path(df.attrs["raw_file_path"])
    manifest_path = Path(df.attrs["manifest_file_path"])

    assert raw_path.is_file()
    assert manifest_path.is_file()
    assert raw_path.read_bytes() == raw_bytes
    assert df.attrs["raw_sha256"] == hashlib.sha256(raw_bytes).hexdigest()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["validation_status"] == "accepted"
    assert manifest["series_code"] == 11
    assert manifest["row_count"] == 2

    # Reinspeção pelo Lakehouse
    record_id = df.attrs["lakehouse_record_id"]
    recovered_bytes, recovered_manifest = storage.read_bronze("bacen_sgs", record_id, extension="json")
    assert recovered_bytes == raw_bytes
    assert recovered_manifest["sha256"] == df.attrs["raw_sha256"]


def test_bacen_sgs_preserves_rejected_raw_payload_on_validation_failure(tmp_path):
    """Astra Directive: 'fonte pode ser reinspecionada e reprovação preservada.'"""
    storage = LakehouseStorageManager(base_dir=str(tmp_path / "lake"))
    miner = BacenSgsMiner(storage=storage)

    # Payload com datas desordenadas (viola monotonicidade temporal)
    corrupted_data = [
        {"data": "12/09/2026", "valor": "0.0450"},
        {"data": "11/09/2026", "valor": "0.0450"},
    ]
    corrupted_bytes = json.dumps(corrupted_data).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = corrupted_bytes

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        with pytest.raises(ValueError, match="sgs_date_order"):
            miner.fetch_series(series_code=11, last_n=2)

    # Prova de preservação da reprovação no disco
    bronze_folder = Path(storage.bronze_dir) / "bacen_sgs"
    saved_payloads = list(bronze_folder.glob("*.json"))
    saved_manifests = list(bronze_folder.glob("*.manifest.json"))
    raw_files = [p for p in saved_payloads if not p.name.endswith(".manifest.json")]

    assert len(raw_files) == 1
    assert len(saved_manifests) == 1

    rejected_payload_file = raw_files[0]
    rejected_manifest_file = saved_manifests[0]

    assert rejected_payload_file.read_bytes() == corrupted_bytes

    manifest = json.loads(rejected_manifest_file.read_text(encoding="utf-8"))
    assert manifest["validation_status"] == "rejected"
    assert manifest["rejection_reason"] == "sgs_date_order"
    assert manifest["sha256"] == hashlib.sha256(corrupted_bytes).hexdigest()


def test_cvm_proventos_persists_raw_csv_and_manifest(tmp_path):
    storage = LakehouseStorageManager(base_dir=str(tmp_path / "lake"))
    miner = CvmEventsMiner(storage=storage)

    csv_sample = (
        "CNPJ_CIA;DENOM_COMERC;COD_ISIN;TIPO_PROVENTO;DT_APROV;DT_CORTE;DT_PAGTO;VALOR_PROVENTO\n"
        "33.000.167/0001-01;PETROBRAS;BRPETRACNPR6;DIVIDENDO;2025-11-20;2025-12-12;2026-01-15;1.250000\n"
    ).encode("utf-8")

    df, meta = miner.ingest_raw_proventos(
        raw_csv_bytes=csv_sample,
        reference_id="cvm_fre_petr4_20260914",
    )

    assert not df.empty
    assert len(df) == 1
    assert Path(meta["file_path"]).is_file()
    assert Path(meta["file_path"]).read_bytes() == csv_sample

    manifest_path = Path(meta["file_path"]).with_name("cvm_fre_petr4_20260914.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["validation_status"] == "accepted"
    assert manifest["row_count"] == 1
    assert manifest["sha256"] == hashlib.sha256(csv_sample).hexdigest()

    # Ingestão de CSV vazio/malformado rejeitado mas preservado
    empty_csv = b""
    with pytest.raises(ValueError, match="cvm_empty_or_malformed_csv"):
        miner.ingest_raw_proventos(
            raw_csv_bytes=empty_csv,
            reference_id="cvm_fre_rejected_001",
        )

    rejected_manifest_path = Path(storage.bronze_dir) / "cvm_proventos" / "cvm_fre_rejected_001.manifest.json"
    assert rejected_manifest_path.is_file()
    rej_meta = json.loads(rejected_manifest_path.read_text(encoding="utf-8"))
    assert rej_meta["validation_status"] == "rejected"
    assert rej_meta["rejection_reason"] == "cvm_empty_or_malformed_csv"


def test_cvm_feed_persists_raw_events_batch(tmp_path):
    storage = LakehouseStorageManager(base_dir=str(tmp_path / "lake"))
    agg = CvmFeedAggregator(tickers=["PETR4", "VALE3"], storage=storage)

    raw_events = [
        {"ticker": "PETR4", "tipo": "FATO_RELEVANTE", "titulo": "Descoberta Pré-Sal", "data": "14/09/2026"},
        {"ticker": "ITUB4", "tipo": "COMUNICADO", "titulo": "Outro Ticker", "data": "14/09/2026"},
    ]

    filtered, meta = agg.ingest_events_batch(raw_events, batch_id="batch_cvm_20260914_01")
    assert len(filtered) == 1
    assert filtered[0]["ticker"] == "PETR4"

    raw_file = Path(meta["file_path"])
    assert raw_file.is_file()

    manifest_file = raw_file.with_name("batch_cvm_20260914_01.manifest.json")
    assert manifest_file.is_file()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["event_count"] == 2
    assert manifest["validation_status"] == "accepted"


def test_lakehouse_inventory_verifies_all_raw_and_rejected_files(tmp_path):
    storage = LakehouseStorageManager(base_dir=str(tmp_path / "lake"))
    miner = BacenSgsMiner(storage=storage)

    # 1. Gerar arquivo válido
    valid_data = [{"data": "10/09/2026", "valor": "0.0450"}]
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(valid_data).encode("utf-8")
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        miner.fetch_series(series_code=11, last_n=1)

    # 2. Gerar arquivo rejeitado
    corrupted = [{"data": "invalid_date", "valor": "0.0450"}]
    mock_resp_corrupted = MagicMock()
    mock_resp_corrupted.read.return_value = json.dumps(corrupted).encode("utf-8")
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_resp_corrupted
        with pytest.raises(ValueError):
            miner.fetch_series(series_code=12, last_n=1)

    # Inventário geral do Lakehouse deve validar ambos os pares sem erros
    inventory = storage.generate_integrity_manifest()
    assert inventory["integrity_ok"] is True
    assert inventory["issues"] == []
    assert inventory["verified_count"] == 2
    assert inventory["bronze_count"] == 2
