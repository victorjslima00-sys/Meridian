"""
Testes unitarios para o Motor de Particionamento Parquet do Lakehouse — Orion Big Data
"""
import os
import pandas as pd
import pytest
from trading_bot.data.lakehouse.partitioned_parquet import PartitionedParquetEngine


def test_parquet_engine_write_and_read(tmp_path):
    engine = PartitionedParquetEngine(base_lake_dir=str(tmp_path / "lakehouse_gold"))
    
    # Simula dados historicos de cotacoes com multiplas datas e tickers
    df = pd.DataFrame({
        "ts": ["2026-09-10", "2026-09-10", "2026-09-11", "2026-09-11"],
        "year_month": ["2026-09", "2026-09", "2026-09", "2026-09"],
        "ticker": ["PETR4", "VALE3", "PETR4", "VALE3"],
        "close": [35.50, 77.20, 35.80, 77.60],
        "volume": [1500000, 2300000, 1800000, 2100000],
    })
    
    manifest = engine.write_partitioned(df, dataset_name="daily_quotes", partition_col="year_month")
    
    assert manifest["status"] == "success"
    assert manifest["total_rows"] == 4
    assert os.path.exists(manifest["dataset_path"])
    
    # Leitura otimizada por particicao
    read_df = engine.read_partition(dataset_name="daily_quotes", partition_value="2026-09")
    assert not read_df.empty
    assert len(read_df) == 4
    assert "PETR4" in read_df["ticker"].values
