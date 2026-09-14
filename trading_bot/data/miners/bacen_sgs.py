"""
Minerador Autonomo de Dados Macroeconomicos — Banco Central do Brasil (SGS)
Head of Data Engineering: Orion
Meridian Technologies
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import math
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, field_validator

from trading_bot.data.lakehouse.storage_manager import LakehouseStorageManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacenSeriesConfig:
    code: int
    name: str
    description: str
    periodicity: str  # D (diario), M (mensal)
    unit: str


SGS_SERIES = {
    "selic_daily": BacenSeriesConfig(11, "Selic Diaria", "Taxa Selic ao dia", "D", "% daily"),
    "cdi_daily": BacenSeriesConfig(12, "CDI Diario", "Taxa CDI ao dia", "D", "% daily"),
    "ipca_monthly": BacenSeriesConfig(433, "IPCA Mensal", "Variacao mensal IPCA", "M", "% monthly"),
    "selic_meta": BacenSeriesConfig(432, "Meta Selic", "Meta Selic fixada pelo Copom", "D", "% annual"),
}


class SgsObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    data: str
    valor: str

    @field_validator("data")
    @classmethod
    def valid_date(cls, value: str) -> str:
        if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
            raise ValueError("invalid_sgs_date")
        datetime.datetime.strptime(value, "%d/%m/%Y")
        return value

    @field_validator("valor")
    @classmethod
    def valid_value(cls, value: str) -> str:
        if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value) or not math.isfinite(float(value)):
            raise ValueError("invalid_sgs_value")
        return value


class BacenSgsMiner:
    """
    Minerador de dados publicos da API do Sistema Gerenciador de Series Temporais (SGS) do Bacen.
    Opera com tolerancia a limites de consulta e regras da API do Bacen.
    """

    BASE_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_code}/dados"
    LAST_N_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_code}/dados/ultimos/{n}"

    def __init__(self, timeout_sec: int = 15, storage: Optional[LakehouseStorageManager] = None):
        self.timeout_sec = timeout_sec
        self.storage = storage or LakehouseStorageManager()

    def fetch_series(
        self,
        series_code: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        last_n: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Busca serie historica via REST API em formato JSON.
        Se last_n nao especificado e sem datas, busca os ultimos 10 registros.
        """
        conf = next((c for c in SGS_SERIES.values() if c.code == series_code), None)
        if conf is None or type(series_code) is not int:
            raise ValueError("unsupported_sgs_series")
        if last_n is not None and (type(last_n) is not int or not 1 <= last_n <= 20 or start_date or end_date):
            raise ValueError("invalid_sgs_query")
        for date_value in (start_date, end_date):
            if date_value is not None:
                SgsObservation.valid_date(date_value)
        if start_date and end_date and datetime.datetime.strptime(start_date, "%d/%m/%Y") > datetime.datetime.strptime(end_date, "%d/%m/%Y"):
            raise ValueError("invalid_sgs_range")
        params = {"formato": "json"}
        if last_n is not None:
            url = self.LAST_N_URL.format(series_code=series_code, n=last_n)
        elif start_date or end_date:
            url = self.BASE_URL.format(series_code=series_code)
            if start_date:
                params["dataInicial"] = start_date
            if end_date:
                params["dataFinal"] = end_date
        else:
            # Bacen SGS limita /ultimos/ a maximo de 20 para certas series
            url = self.LAST_N_URL.format(series_code=series_code, n=10)

        query_str = urllib.parse.urlencode(params)
        full_url = f"{url}?{query_str}"

        req = urllib.request.Request(
            full_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
                "Accept": "application/json, text/plain, */*",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw_bytes = resp.read()
        except Exception as exc:
            logger.warning("Falha ao minerar serie SGS %s", series_code)
            raise ValueError("sgs_fetch_unavailable") from exc
        retrieved = datetime.datetime.now(datetime.timezone.utc).isoformat()
        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        ts_slug = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        base_record_id = f"sgs_{series_code}_{ts_slug}_{raw_hash[:8]}"
        record_id = base_record_id
        counter = 0
        while True:
            candidate_id = record_id if counter == 0 else f"{base_record_id}_{counter}"
            folder = Path(self.storage.bronze_dir) / "bacen_sgs"
            if not (folder / f"{candidate_id}.json").exists() and not (folder / f"{candidate_id}.manifest.json").exists():
                record_id = candidate_id
                break
            counter += 1

        validation_error: Optional[ValueError] = None
        df: Optional[pd.DataFrame] = None
        method: Optional[str] = None
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
            if not isinstance(data, list) or not data:
                raise ValueError("sgs_empty_or_invalid")
            observations = [SgsObservation.model_validate(row) for row in data]
            df = pd.DataFrame([row.model_dump() for row in observations])
            df["valor"] = df["valor"].map(float)
            df["data_parsed"] = pd.to_datetime(df["data"], format="%d/%m/%Y", errors="raise")
            dates = df["data_parsed"]
            if dates.duplicated().any() or not dates.is_monotonic_increasing:
                raise ValueError("sgs_date_order")
            if start_date and (dates < pd.to_datetime(start_date, format="%d/%m/%Y")).any():
                raise ValueError("sgs_outside_range")
            if end_date and (dates > pd.to_datetime(end_date, format="%d/%m/%Y")).any():
                raise ValueError("sgs_outside_range")
            if conf.unit == "% daily":
                if (df["valor"] <= -100).any():
                    raise ValueError("sgs_rate_domain")
                df["taxa_anual_estimada"] = df["valor"].map(lambda v: ((1 + v / 100) ** 252 - 1) * 100)
                if not df["taxa_anual_estimada"].map(math.isfinite).all():
                    raise ValueError("sgs_rate_overflow")
                method = "constant_daily_rate_compounded_252_business_days_not_forecast"
            elif conf.unit == "% annual":
                df["taxa_anual_estimada"] = df["valor"]
                method = "source_annual_rate_unchanged"
            else:
                df["taxa_anual_estimada"] = None
                method = "not_applicable_monthly_inflation"
        except (ValueError, TypeError, OverflowError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("sgs_"):
                validation_error = exc
            else:
                validation_error = ValueError("sgs_invalid_response")

        if validation_error is not None:
            self.storage.save_bronze_raw(
                dataset_name="bacen_sgs",
                record_id=record_id,
                raw_bytes=raw_bytes,
                extension="json",
                metadata={
                    "series_code": series_code,
                    "source_url": full_url,
                    "retrieved_at_utc": retrieved,
                    "validation_status": "rejected",
                    "rejection_reason": str(validation_error),
                },
            )
            raise validation_error

        bronze_meta = self.storage.save_bronze_raw(
            dataset_name="bacen_sgs",
            record_id=record_id,
            raw_bytes=raw_bytes,
            extension="json",
            metadata={
                "series_code": series_code,
                "source_url": full_url,
                "retrieved_at_utc": retrieved,
                "validation_status": "accepted",
                "row_count": len(df),
            },
        )
        df.attrs.update(
            source_url=full_url,
            raw_sha256=raw_hash,
            raw_file_path=bronze_meta["file_path"],
            manifest_file_path=str(Path(bronze_meta["file_path"]).with_name(f"{record_id}.manifest.json")),
            lakehouse_record_id=record_id,
            retrieved_at_utc=retrieved,
            unit=conf.unit,
            periodicity=conf.periodicity,
            series_code=series_code,
            annualization_method=method,
            collector="BacenSgsMiner",
            authenticity="not_independently_verified",
            publication_timestamp=None,
            point_in_time_verified=False,
        )
        return df

    def get_macro_snapshot(self) -> dict[str, Any]:
        """
        Gera snapshot executivo com as series primarias para a tomada de decisao da Astra.
        """
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        snapshot_records: dict[str, Any] = {
            "timestamp_utc": now_utc,
            "generator": "Orion-BacenSgsMiner",
        }

        for key, conf in SGS_SERIES.items():
            try:
                df = self.fetch_series(conf.code, last_n=1)
                if df.empty:
                    raise ValueError("sgs_empty_response")
                last_row = df.iloc[-1]
                snapshot_records[key] = {
                    "status": "available",
                    "code": conf.code,
                    "data": str(last_row["data"]),
                    "valor": float(last_row["valor"]),
                    "unit": conf.unit,
                    "taxa_anual": None if conf.unit == "% monthly" else float(last_row["taxa_anual_estimada"]),
                    "raw_file_path": df.attrs.get("raw_file_path"),
                    "raw_sha256": df.attrs.get("raw_sha256"),
                    "provenance": dict(df.attrs),
                }
            except ValueError:
                snapshot_records[key] = {"status": "unavailable", "code": conf.code,
                                         "unit": conf.unit, "valor": None, "taxa_anual": None,
                                         "data": None, "reason": "sgs_unavailable_or_invalid"}

        serialized = json.dumps(snapshot_records, sort_keys=True)
        snapshot_records["manifest_sha256"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return snapshot_records
