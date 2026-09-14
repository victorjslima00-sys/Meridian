"""Unit tests for DataReconciliationAgent.

Validates exact comparisons, documented events with SHA-256 hashes,
absence of silent imputations, and strict fail-closed behavior on mismatch.
"""
import csv
import json
from pathlib import Path
import sqlite3

import pytest
from pydantic import ValidationError

from scripts.reconcile_feeds import (
    compute_file_sha256,
    export_reconciliation_report,
    load_events_file,
    load_from_cotahist,
    load_from_csv,
    load_from_json,
    load_from_sqlite,
    main as reconcile_main,
    reconcile_feeds,
)
from trading_bot.data.data_reconciliation import (
    DataReconciliationAgent,
    EventDocument,
    ObservationRecord,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_DOC = "c" * 64


def make_record(ticker="PETR4", dt="2026-09-11", price=38.20, unit="BRL/share", src="source_a", sha=HASH_A):
    return ObservationRecord(
        ticker=ticker,
        date=dt,
        price=price,
        unit=unit,
        source_ref=src,
        source_sha256=sha,
    )


def test_exact_matches_reconcile_completely():
    agent = DataReconciliationAgent(tolerance=0.001)
    series_a = [
        make_record(dt="2026-09-09", price=37.50, src="feed_xp"),
        make_record(dt="2026-09-10", price=38.00, src="feed_xp"),
        make_record(dt="2026-09-11", price=38.20, src="feed_xp"),
    ]
    series_b = [
        make_record(dt="2026-09-09", price=37.50, src="b3_cotahist", sha=HASH_B),
        make_record(dt="2026-09-10", price=38.00, src="b3_cotahist", sha=HASH_B),
        make_record(dt="2026-09-11", price=38.20, src="b3_cotahist", sha=HASH_B),
    ]

    report = agent.reconcile(series_a, series_b)

    assert report.status == "RECONCILED"
    assert report.total_dates == 3
    assert report.exact_matches == 3
    assert report.documented_matches == 0
    assert report.unexplained_mismatches == 0
    assert report.missing_data_count == 0
    assert report.max_absolute_residual == 0.0


def test_missing_date_is_flagged_never_imputed():
    agent = DataReconciliationAgent()
    series_a = [
        make_record(dt="2026-09-10", price=38.00),
        make_record(dt="2026-09-11", price=38.20),
    ]
    series_b = [
        # Missing 2026-09-10
        make_record(dt="2026-09-11", price=38.20, src="b3_cotahist", sha=HASH_B),
        make_record(dt="2026-09-12", price=38.40, src="b3_cotahist", sha=HASH_B),
    ]

    report = agent.reconcile(series_a, series_b)

    assert report.status == "DISCREPANCY_DETECTED"
    assert report.missing_data_count == 2
    assert report.exact_matches == 1

    missing_items = [it for it in report.items if it.status == "MISSING_DATA"]
    assert len(missing_items) == 2
    assert missing_items[0].date == "2026-09-10"
    assert missing_items[0].price_a == 38.00
    assert missing_items[0].price_b is None
    assert missing_items[0].reason == "missing_in_source_b"


def test_unexplained_price_delta_fails_reconciliation():
    agent = DataReconciliationAgent(tolerance=0.01)
    series_a = [make_record(dt="2026-09-11", price=38.20)]
    series_b = [make_record(dt="2026-09-11", price=38.50, src="b3_cotahist", sha=HASH_B)]

    report = agent.reconcile(series_a, series_b)

    assert report.status == "DISCREPANCY_DETECTED"
    assert report.unexplained_mismatches == 1
    assert report.exact_matches == 0
    item = report.items[0]
    assert item.status == "UNEXPLAINED_MISMATCH"
    assert item.price_delta == 0.30
    assert item.residual_delta == 0.30


def test_documented_corporate_action_reconciles():
    agent = DataReconciliationAgent(tolerance=0.001)
    # Price difference of R$ 1.15 exactly matches CVM dividend document
    series_a = [make_record(dt="2026-09-11", price=38.20)]
    series_b = [make_record(dt="2026-09-11", price=37.05, src="b3_cotahist", sha=HASH_B)]

    events = [
        EventDocument(
            ticker="PETR4",
            event_date="2026-09-11",
            event_type="DIVIDEND",
            cash_amount=1.15,
            document_ref="CVM_FR_20260911_PETR4.pdf",
            document_sha256=HASH_DOC,
        )
    ]

    report = agent.reconcile(series_a, series_b, events=events)

    assert report.status == "RECONCILED"
    assert report.documented_matches == 1
    assert report.unexplained_mismatches == 0
    item = report.items[0]
    assert item.status == "DOCUMENTED_MATCH"
    assert item.documented_adjustments == 1.15
    assert item.residual_delta == 0.0


def test_insufficient_documented_event_leaves_residual_mismatch():
    agent = DataReconciliationAgent(tolerance=0.001)
    # Price delta is 1.50, but documented dividend is only 1.00 -> residual 0.50
    series_a = [make_record(dt="2026-09-11", price=38.20)]
    series_b = [make_record(dt="2026-09-11", price=36.70, src="b3_cotahist", sha=HASH_B)]

    events = [
        EventDocument(
            ticker="PETR4",
            event_date="2026-09-11",
            event_type="DIVIDEND",
            cash_amount=1.00,
            document_ref="CVM_FR_INCOMPLETE.pdf",
            document_sha256=HASH_DOC,
        )
    ]

    report = agent.reconcile(series_a, series_b, events=events)

    assert report.status == "DISCREPANCY_DETECTED"
    assert report.unexplained_mismatches == 1
    item = report.items[0]
    assert item.status == "UNEXPLAINED_MISMATCH"
    assert item.residual_delta == 0.50


def test_unit_mismatch_raises_error():
    agent = DataReconciliationAgent()
    series_a = [make_record(unit="BRL/share")]
    series_b = [make_record(unit="USD/share", src="adr_feed", sha=HASH_B)]

    with pytest.raises(ValueError, match="unit_mismatch"):
        agent.reconcile(series_a, series_b)


def test_mixed_tickers_raises_error():
    agent = DataReconciliationAgent()
    series_a = [make_record(ticker="PETR4"), make_record(ticker="VALE3")]
    series_b = [make_record(ticker="PETR4", sha=HASH_B)]

    with pytest.raises(ValueError, match="mixed_tickers_found"):
        agent.reconcile(series_a, series_b)


def test_non_positive_price_rejected():
    with pytest.raises(ValidationError):
        make_record(price=-10.0)

    with pytest.raises(ValidationError):
        make_record(price=0.0)


def test_split_ratio_schema_validation():
    # Valid split_ratio
    ev = EventDocument(
        ticker="PETR4",
        event_date="2026-09-11",
        event_type="SPLIT",
        split_ratio=2.0,
        document_ref="CVM_SPLIT_20260911.pdf",
        document_sha256=HASH_DOC,
    )
    assert ev.split_ratio == 2.0
    assert ev.cash_amount == 0.0

    # Default split_ratio is 1.0
    ev_def = EventDocument(
        ticker="PETR4",
        event_date="2026-09-11",
        event_type="DIVIDEND",
        cash_amount=1.50,
        document_ref="CVM_DIV.pdf",
        document_sha256=HASH_DOC,
    )
    assert ev_def.split_ratio == 1.0

    # Zero split_ratio rejected
    with pytest.raises(ValidationError):
        EventDocument(
            ticker="PETR4",
            event_date="2026-09-11",
            event_type="SPLIT",
            split_ratio=0.0,
            document_ref="CVM_SPLIT.pdf",
            document_sha256=HASH_DOC,
        )

    # Negative split_ratio rejected
    with pytest.raises(ValidationError):
        EventDocument(
            ticker="PETR4",
            event_date="2026-09-11",
            event_type="SPLIT",
            split_ratio=-2.0,
            document_ref="CVM_SPLIT.pdf",
            document_sha256=HASH_DOC,
        )


def test_split_corporate_action_reconciles_multiplicative():
    agent = DataReconciliationAgent(tolerance=0.001)
    # Feed A has pre-split price 40.00; Feed B has post-split price 20.00 (2:1 split)
    series_a = [make_record(dt="2026-09-11", price=40.00)]
    series_b = [make_record(dt="2026-09-11", price=20.00, src="b3_cotahist", sha=HASH_B)]

    events = [
        EventDocument(
            ticker="PETR4",
            event_date="2026-09-11",
            event_type="SPLIT",
            split_ratio=2.0,
            document_ref="CVM_SPLIT_PETR4_2026.pdf",
            document_sha256=HASH_DOC,
        )
    ]

    report = agent.reconcile(series_a, series_b, events=events)

    assert report.status == "RECONCILED"
    assert report.documented_matches == 1
    assert report.unexplained_mismatches == 0
    item = report.items[0]
    assert item.status == "DOCUMENTED_MATCH"
    assert item.documented_adjustments == 20.00
    assert item.residual_delta == 0.0


def test_reverse_split_corporate_action_reconciles():
    agent = DataReconciliationAgent(tolerance=0.001)
    # 10:1 reverse split (agrupamento): 10 shares into 1 (ratio = 0.1)
    # Feed A: 5.00 -> Feed B: 50.00 (5.00 / 0.1 = 50.00)
    series_a = [make_record(dt="2026-09-11", price=5.00)]
    series_b = [make_record(dt="2026-09-11", price=50.00, src="b3_cotahist", sha=HASH_B)]

    events = [
        EventDocument(
            ticker="PETR4",
            event_date="2026-09-11",
            event_type="SPLIT",
            split_ratio=0.1,
            document_ref="CVM_REVERSE_SPLIT_PETR4.pdf",
            document_sha256=HASH_DOC,
        )
    ]

    report = agent.reconcile(series_a, series_b, events=events)

    assert report.status == "RECONCILED"
    assert report.documented_matches == 1
    assert report.items[0].residual_delta == 0.0
    assert report.max_absolute_residual == 0.0


def test_split_with_unexplained_residual_mismatch():
    agent = DataReconciliationAgent(tolerance=0.001)
    # Feed A: 40.00 -> with 2:1 split should be 20.00, but Feed B is 20.50
    series_a = [make_record(dt="2026-09-11", price=40.00)]
    series_b = [make_record(dt="2026-09-11", price=20.50, src="b3_cotahist", sha=HASH_B)]

    events = [
        EventDocument(
            ticker="PETR4",
            event_date="2026-09-11",
            event_type="SPLIT",
            split_ratio=2.0,
            document_ref="CVM_SPLIT.pdf",
            document_sha256=HASH_DOC,
        )
    ]

    report = agent.reconcile(series_a, series_b, events=events)

    assert report.status == "DISCREPANCY_DETECTED"
    assert report.unexplained_mismatches == 1
    item = report.items[0]
    assert item.status == "UNEXPLAINED_MISMATCH"
    assert item.residual_delta == 0.50


def test_combined_split_and_cash_dividend():
    agent = DataReconciliationAgent(tolerance=0.001)
    # 2:1 split (40.00 -> 20.00) AND 1.00 cash dividend (20.00 - 1.00 = 19.00)
    series_a = [make_record(dt="2026-09-11", price=40.00)]
    series_b = [make_record(dt="2026-09-11", price=19.00, src="b3_cotahist", sha=HASH_B)]

    events = [
        EventDocument(
            ticker="PETR4",
            event_date="2026-09-11",
            event_type="SPLIT",
            split_ratio=2.0,
            document_ref="CVM_SPLIT.pdf",
            document_sha256=HASH_DOC,
        ),
        EventDocument(
            ticker="PETR4",
            event_date="2026-09-11",
            event_type="DIVIDEND",
            cash_amount=1.00,
            document_ref="CVM_DIVIDEND.pdf",
            document_sha256=HASH_DOC,
        ),
    ]

    report = agent.reconcile(series_a, series_b, events=events)

    assert report.status == "RECONCILED"
    assert report.documented_matches == 1
    item = report.items[0]
    assert item.status == "DOCUMENTED_MATCH"
    assert item.residual_delta == 0.0
    assert item.documented_adjustments == 21.00


def test_load_observations_from_csv_and_json(tmp_path):
    # CSV Feed
    csv_file = tmp_path / "feed.csv"
    csv_file.write_text(
        "ticker,date,close,volume\n"
        "PETR4,2026-09-10,38.00,10000\n"
        "PETR4,2026-09-11,38.50,15000\n",
        encoding="utf-8",
    )
    records_csv = load_from_csv(csv_file, ticker="PETR4")
    assert len(records_csv) == 2
    assert records_csv[0].price == 38.00
    assert records_csv[1].price == 38.50
    assert len(records_csv[0].source_sha256) == 64

    # JSON Feed
    json_file = tmp_path / "feed.json"
    json_file.write_text(
        json.dumps([
            {"ticker": "PETR4", "date": "2026-09-10", "price": 38.00, "volume": 10000},
            {"ticker": "PETR4", "date": "2026-09-11", "price": 38.50, "volume": 15000},
        ]),
        encoding="utf-8",
    )
    records_json = load_from_json(json_file, ticker="PETR4")
    assert len(records_json) == 2
    assert records_json[0].price == 38.00
    assert len(records_json[0].source_sha256) == 64


def test_load_observations_from_sqlite(tmp_path):
    db_file = tmp_path / "test_feed.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE ohlcv (ticker TEXT, ts DATE, o REAL, h REAL, l REAL, c REAL, v REAL, adj_close REAL, PRIMARY KEY (ticker, ts))"
    )
    conn.execute(
        "INSERT INTO ohlcv VALUES ('PETR4', '2026-09-10', 37.0, 38.5, 36.8, 38.0, 50000.0, 38.0)"
    )
    conn.execute(
        "INSERT INTO ohlcv VALUES ('VALE3', '2026-09-10', 60.0, 61.5, 59.8, 61.0, 30000.0, 61.0)"
    )
    conn.commit()
    conn.close()

    records = load_from_sqlite(db_file, ticker="PETR4")
    assert len(records) == 1
    assert records[0].ticker == "PETR4"
    assert records[0].price == 38.0
    assert records[0].date == "2026-09-10"
    assert len(records[0].source_sha256) == 64


def test_load_observations_from_cotahist_export(tmp_path):
    export_dir = tmp_path / "cotahist_exp"
    export_dir.mkdir()
    manifest_file = export_dir / "manifest.json"
    manifest_file.write_text(
        json.dumps({
            "source_sha256": HASH_B,
            "ready_for_backtest": False,
            "structural_validation": "passed",
        }),
        encoding="utf-8",
    )
    quotes_file = export_dir / "quotes.csv"
    quotes_file.write_text(
        "trading_date,ticker,market,bdi,issuer,specification,currency,open,high,low,mean,close,bid,ask,trades,quantity,financial_volume,quotation_factor,isin,distribution,quality_flags\n"
        "2026-09-10,PETR4,10,02,PETROBRAS,PN,R$,37.00,38.50,36.80,37.80,38.00,37.90,38.00,1000,50000,1890000.00,1,BRPETRACNPR6,100,\n",
        encoding="utf-8",
    )

    records = load_from_cotahist(export_dir, ticker="PETR4")
    assert len(records) == 1
    assert records[0].ticker == "PETR4"
    assert records[0].date == "2026-09-10"
    assert records[0].price == 38.00
    assert records[0].source_sha256 == HASH_B


def test_export_reconciliation_report_deterministic(tmp_path):
    report_file = tmp_path / "reconciliation_report.json"
    agent = DataReconciliationAgent(tolerance=0.001)
    rec_a = [make_record(dt="2026-09-10", price=38.00)]
    rec_b = [make_record(dt="2026-09-10", price=38.00, src="b3_cotahist", sha=HASH_B)]
    report = agent.reconcile(rec_a, rec_b)

    meta = export_reconciliation_report(report, report_file)
    assert report_file.is_file()
    assert meta["status"] == "RECONCILED"
    assert meta["exact_matches"] == 1
    assert len(meta["report_sha256"]) == 64
    assert compute_file_sha256(report_file) == meta["report_sha256"]


def test_reconcile_feeds_cli_end_to_end(tmp_path):
    # Prepare Source A CSV
    src_a_file = tmp_path / "source_a.csv"
    src_a_file.write_text(
        "ticker,date,close\n"
        "PETR4,2026-09-10,38.00\n"
        "PETR4,2026-09-11,40.00\n",
        encoding="utf-8",
    )

    # Prepare Source B SQLite
    db_file = tmp_path / "source_b.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE ohlcv (ticker TEXT, ts DATE, o REAL, h REAL, l REAL, c REAL, v REAL, adj_close REAL, PRIMARY KEY (ticker, ts))"
    )
    conn.execute("INSERT INTO ohlcv VALUES ('PETR4', '2026-09-10', 38.0, 38.0, 38.0, 38.00, 1000.0, 38.0)")
    conn.execute("INSERT INTO ohlcv VALUES ('PETR4', '2026-09-11', 20.0, 20.0, 20.0, 20.00, 1000.0, 20.0)")
    conn.commit()
    conn.close()

    # Prepare Events JSON (2:1 split on 2026-09-11)
    events_file = tmp_path / "events.json"
    events_file.write_text(
        json.dumps([
            {
                "ticker": "PETR4",
                "event_date": "2026-09-11",
                "event_type": "SPLIT",
                "cash_amount": 0.0,
                "split_ratio": 2.0,
                "document_ref": "CVM_SPLIT.pdf",
                "document_sha256": HASH_DOC,
            }
        ]),
        encoding="utf-8",
    )

    out_report = tmp_path / "out_report.json"

    # Run CLI: Should succeed with 0
    ret = reconcile_main([
        "--ticker", "PETR4",
        "--source-a", str(src_a_file),
        "--source-b", str(db_file),
        "--events", str(events_file),
        "--output", str(out_report),
    ])
    assert ret == 0
    assert out_report.is_file()

    saved_data = json.loads(out_report.read_text(encoding="utf-8"))
    assert saved_data["status"] == "RECONCILED"
    assert saved_data["exact_matches"] == 1
    assert saved_data["documented_matches"] == 1
    assert saved_data["unexplained_mismatches"] == 0


def test_reconcile_feeds_cli_discrepancy_and_missing_data(tmp_path):
    src_a_file = tmp_path / "source_a.csv"
    src_a_file.write_text(
        "ticker,date,close\n"
        "PETR4,2026-09-10,38.00\n"
        "PETR4,2026-09-11,40.00\n",
        encoding="utf-8",
    )

    src_b_file = tmp_path / "source_b.csv"
    # Discrepancy on 2026-09-10 (38.50 vs 38.00) and missing 2026-09-11, extra 2026-09-12
    src_b_file.write_text(
        "ticker,date,close\n"
        "PETR4,2026-09-10,38.50\n"
        "PETR4,2026-09-12,39.00\n",
        encoding="utf-8",
    )

    out_report = tmp_path / "out_report_disc.json"

    # Run CLI without --allow-discrepancies: should exit 1
    ret = reconcile_main([
        "--ticker", "PETR4",
        "--source-a", str(src_a_file),
        "--source-b", str(src_b_file),
        "--output", str(out_report),
    ])
    assert ret == 1

    saved = json.loads(out_report.read_text(encoding="utf-8"))
    assert saved["status"] == "DISCREPANCY_DETECTED"
    assert saved["unexplained_mismatches"] == 1
    assert saved["missing_data_count"] == 2

    # Run CLI with --allow-discrepancies: should exit 0
    ret_allow = reconcile_main([
        "--ticker", "PETR4",
        "--source-a", str(src_a_file),
        "--source-b", str(src_b_file),
        "--output", str(out_report),
        "--allow-discrepancies",
    ])
    assert ret_allow == 0

