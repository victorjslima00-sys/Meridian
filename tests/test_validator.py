import pytest
import pandas as pd
from datetime import date, timedelta
from trading_bot.data.validator import validate_ohlcv, validate_universe

def test_validate_ohlcv_empty():
    df = pd.DataFrame()
    report = validate_ohlcv(df, "TEST3")
    assert not report.ok
    assert len(report.errors) == 1
    assert report.errors[0].issue_type == "empty"

def test_validate_ohlcv_gap():
    # Gap de 6 dias
    data = [
        {"ts": date(2023, 1, 1), "c": 100, "v": 1000},
        {"ts": date(2023, 1, 8), "c": 101, "v": 1000},
    ]
    df = pd.DataFrame(data)
    report = validate_ohlcv(df, "TEST3")
    gap_issues = [i for i in report.issues if i.issue_type == "gap"]
    assert len(gap_issues) == 1
    assert gap_issues[0].severity == "warning"

def test_validate_ohlcv_zero_volume():
    data = [
        {"ts": date(2023, 1, 1), "c": 100, "v": 0},
        {"ts": date(2023, 1, 2), "c": 101, "v": 1000},
    ]
    df = pd.DataFrame(data)
    report = validate_ohlcv(df, "TEST3")
    vol_issues = [i for i in report.issues if i.issue_type == "zero_volume"]
    assert len(vol_issues) == 1
    assert vol_issues[0].severity == "warning"

def test_validate_ohlcv_large_move():
    # Variação de >40% -> error
    data = [
        {"ts": date(2023, 1, 1), "c": 100, "v": 1000},
        {"ts": date(2023, 1, 2), "c": 150, "v": 1000},
    ]
    df = pd.DataFrame(data)
    report = validate_ohlcv(df, "TEST3")
    move_issues = [i for i in report.issues if i.issue_type == "large_move"]
    assert len(move_issues) == 1
    assert move_issues[0].severity == "error"

def test_validate_ohlcv_possible_split():
    # Preço cai >40% mas volume não aumenta (cai tbm) -> error
    data = [
        {"ts": date(2023, 1, 1), "c": 100, "v": 1000},
        {"ts": date(2023, 1, 2), "c": 50, "v": 1000},
    ]
    df = pd.DataFrame(data)
    report = validate_ohlcv(df, "TEST3")
    split_issues = [i for i in report.issues if i.issue_type == "possible_split"]
    assert len(split_issues) == 1
    assert split_issues[0].severity == "error"

def test_validate_universe():
    data = {
        "TEST3": pd.DataFrame([{"ts": date(2023,1,1), "c":100, "v":1000}]),
        "ERR3": pd.DataFrame([{"ts": date(2023,1,1), "c":100, "v":1000}, {"ts": date(2023,1,2), "c":50, "v":1000}])
    }
    reports = validate_universe(data)
    assert len(reports) == 2
    assert reports["TEST3"].ok
    assert not reports["ERR3"].ok
