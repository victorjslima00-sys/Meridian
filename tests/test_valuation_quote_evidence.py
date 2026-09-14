"""Synthetic fixtures: scalar prices are not timestamped market evidence."""
import sqlite3
from datetime import datetime, timezone

import pytest

from trading_bot.data.valuation_snapshot import create_valuation_snapshot


@pytest.fixture
def valuation_db(tmp_path):
    path = tmp_path / "synthetic.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE portfolio (id INTEGER, saldo_disponivel REAL, em_posicoes REAL, patrimonio_total REAL, margem_operavel REAL)")
        conn.execute("INSERT INTO portfolio VALUES (1, 800, 30, 800, NULL)")
        conn.execute("CREATE TABLE trades (ticker TEXT, shares REAL, entry_price REAL, status TEXT)")
        conn.execute("INSERT INTO trades VALUES ('SYNTHETIC', 1, 30, 'active')")
    return path


@pytest.mark.parametrize("price", [32.5, float("nan"), float("inf"), True])
def test_scalar_quote_cannot_acquire_source_or_observation_time(valuation_db, price):
    clock = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    snapshot = create_valuation_snapshot(
        db_path=valuation_db, price_provider=lambda _: price, clock_now=clock,
    )
    assert snapshot.is_valid is False
    assert snapshot.equity is None
    assert snapshot.mtm_total is None
    assert snapshot.reason == "quote_evidence_required_for_SYNTHETIC"
    item = snapshot.active_positions[0]
    assert item.current_price is None
    assert item.quote_source is None
    assert item.quote_observed_at is None
    assert item.pnl_monetario is None


def test_empty_portfolio_does_not_require_market_quotes(valuation_db):
    with sqlite3.connect(valuation_db) as conn:
        conn.execute("DELETE FROM trades")
        conn.execute("UPDATE portfolio SET em_posicoes=0")
    def forbidden(_):
        pytest.fail("No quote should be requested without positions")
    snapshot = create_valuation_snapshot(db_path=valuation_db, price_provider=forbidden)
    assert snapshot.is_valid is True
    assert snapshot.equity == 800
    assert snapshot.active_positions == []
