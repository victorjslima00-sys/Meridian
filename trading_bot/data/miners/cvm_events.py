"""
Minerador Autonomo de Proventos e Eventos Corporativos — CVM Dados Abertos
Head of Data Engineering: Orion
Meridian Technologies
"""
from __future__ import annotations

import datetime
import hashlib
import io
import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from trading_bot.data.lakehouse.storage_manager import LakehouseStorageManager

logger = logging.getLogger(__name__)


class CvmEventsMiner:
    """
    Minerador para o portal de Dados Abertos da Comissao de Valores Mobiliarios (CVM).
    Responsavel por mapear dividendos, JCP, bonificacoes e datas de corte dos ativos sob cobertura.
    """

    CVM_BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/"

    def __init__(self, timeout_sec: int = 20, storage: Optional[LakehouseStorageManager] = None):
        self.timeout_sec = timeout_sec
        self.storage = storage or LakehouseStorageManager()

    def ingest_raw_proventos(
        self,
        raw_csv_bytes: bytes,
        reference_id: str,
        source_url: Optional[str] = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """
        Persiste os bytes brutos do CSV da CVM no Lakehouse na camada Bronze
        com calculo de SHA-256 e gravacao de manifesto, antes de converter em DataFrame.
        Se os bytes forem corrompidos ou ilegiveis, preserva no Lakehouse com
        validation_status='rejected' antes de levantar ValueError.
        """
        if not isinstance(raw_csv_bytes, (bytes, bytearray)):
            raise TypeError("raw_csv_bytes_must_be_bytes")

        retrieved = datetime.datetime.now(datetime.timezone.utc).isoformat()
        raw_hash = hashlib.sha256(raw_csv_bytes).hexdigest()

        raw_text: Optional[str] = None
        for enc in ("utf-8", "latin1"):
            try:
                raw_text = raw_csv_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue

        if raw_text is None:
            meta = self.storage.save_bronze_raw(
                dataset_name="cvm_proventos",
                record_id=reference_id,
                raw_bytes=raw_csv_bytes,
                extension="csv",
                metadata={
                    "source_url": source_url or self.CVM_BASE_URL,
                    "retrieved_at_utc": retrieved,
                    "validation_status": "rejected",
                    "rejection_reason": "cvm_csv_decode_error",
                },
            )
            raise ValueError("cvm_csv_decode_error")

        df = self.parse_proventos_data(raw_text)
        if df.empty:
            meta = self.storage.save_bronze_raw(
                dataset_name="cvm_proventos",
                record_id=reference_id,
                raw_bytes=raw_csv_bytes,
                extension="csv",
                metadata={
                    "source_url": source_url or self.CVM_BASE_URL,
                    "retrieved_at_utc": retrieved,
                    "validation_status": "rejected",
                    "rejection_reason": "cvm_empty_or_malformed_csv",
                },
            )
            raise ValueError("cvm_empty_or_malformed_csv")

        meta = self.storage.save_bronze_raw(
            dataset_name="cvm_proventos",
            record_id=reference_id,
            raw_bytes=raw_csv_bytes,
            extension="csv",
            metadata={
                "source_url": source_url or self.CVM_BASE_URL,
                "retrieved_at_utc": retrieved,
                "validation_status": "accepted",
                "row_count": len(df),
            },
        )
        df.attrs.update(
            source_url=source_url or self.CVM_BASE_URL,
            raw_sha256=raw_hash,
            raw_file_path=meta["file_path"],
            manifest_file_path=str(Path(meta["file_path"]).with_name(f"{reference_id}.manifest.json")),
            lakehouse_record_id=reference_id,
            retrieved_at_utc=retrieved,
            collector="CvmEventsMiner",
            authenticity="not_independently_verified",
        )
        return df, meta

    def parse_proventos_data(self, raw_csv_text: str) -> pd.DataFrame:
        """
        Converte texto CSV bruto da CVM em DataFrame sanitizado.
        """
        try:
            df = pd.read_csv(io.StringIO(raw_csv_text), sep=";", encoding="utf-8")
        except Exception:
            try:
                df = pd.read_csv(io.StringIO(raw_csv_text), sep=";", encoding="latin1")
            except Exception as e:
                logger.error("Falha ao decodificar CSV CVM: %s", e)
                return pd.DataFrame()

        if "VALOR_PROVENTO" in df.columns:
            df["VALOR_PROVENTO"] = pd.to_numeric(
                df["VALOR_PROVENTO"].astype(str).str.replace(",", "."), errors="coerce"
            )

        return df

    def filter_by_company(self, df: pd.DataFrame, company_query: str) -> pd.DataFrame:
        """
        Filtra registros por nome comercial ou razao social da companhia.
        """
        if df.empty or "DENOM_COMERC" not in df.columns:
            return pd.DataFrame()

        mask = df["DENOM_COMERC"].str.contains(company_query, case=False, na=False)
        return df[mask].copy().reset_index(drop=True)
