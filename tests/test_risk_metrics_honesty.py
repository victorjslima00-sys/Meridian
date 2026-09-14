"""Synthetic database fixtures; no market observations or returns asserted."""
import sqlite3

import pytest

from backend.app.data import database


def metrics_for(monkeypatch, tmp_path, values):
    path = tmp_path / "metrics.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE trades (status TEXT, pnl_pct REAL)")
        conn.executemany("INSERT INTO trades VALUES ('closed', ?)", [(v,) for v in values])
    monkeypatch.setattr(database, "get_connection", lambda: sqlite3.connect(path))
    return database.get_risk_metrics()


def test_portfolio_risk_is_not_fabricated_from_individual_trade_returns(monkeypatch, tmp_path):
    result = metrics_for(monkeypatch, tmp_path, [10, -2, -3, 0])
    for key in ("sharpe", "sortino", "calmar", "max_drawdown_pct", "var_95_daily"):
        assert result[key] is None, key
    assert result["win_rate"] == .25
    assert result["avg_win"] == 10
    assert result["avg_loss"] == -2.5
    assert result["_metadata"]["sample_count"] == 4
    assert result["_metadata"]["source"] == "sqlite:trades/status=closed/pnl_pct"
    assert result["_metadata"]["generated_at_utc"]
    assert result["_metadata"]["owner"]


@pytest.mark.parametrize("values", [[], [None], [float("inf")], ["invalid"]])
def test_missing_or_invalid_sample_is_unavailable_not_zero(monkeypatch, tmp_path, values):
    result = metrics_for(monkeypatch, tmp_path, values)
    assert all(result[key] is None for key in ("win_rate", "avg_win", "avg_loss"))


def test_partial_invalid_sample_is_not_silently_dropped(monkeypatch, tmp_path):
    result = metrics_for(monkeypatch, tmp_path, [10, None, -2])
    assert result["win_rate"] is None
    assert result["_metadata"]["invalid_count"] == 1


def test_absent_loss_group_is_unavailable(monkeypatch, tmp_path):
    result = metrics_for(monkeypatch, tmp_path, [10, 0])
    assert result["win_rate"] == .5
    assert result["avg_loss"] is None
