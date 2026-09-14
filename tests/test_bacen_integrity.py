"""Synthetic HTTP fixtures; no market observation or network request."""
import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest

from trading_bot.data.miners.bacen_sgs import BacenSgsMiner


def fetch(code, rows):
    raw = json.dumps(rows).encode()
    response = MagicMock()
    response.read.return_value = raw
    with patch("urllib.request.urlopen") as opener:
        opener.return_value.__enter__.return_value = response
        return BacenSgsMiner().fetch_series(code), raw


def test_monthly_not_annualized_and_raw_provenance():
    df, raw = fetch(433, [{"data": "01/08/2026", "valor": "-0.2"}])
    assert df["taxa_anual_estimada"].iloc[0] is None
    assert df.attrs["unit"] == "% monthly"
    assert df.attrs["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert df.attrs["retrieved_at_utc"]
    assert "bcdata.sgs.433" in df.attrs["source_url"]


def test_annual_meta_not_compounded():
    df, _ = fetch(432, [{"data": "01/08/2026", "valor": "15"}])
    assert df["taxa_anual_estimada"].iloc[0] == 15


@pytest.mark.parametrize("bad", [
    {"data": "bad", "valor": "1"},
    {"data": "01/08/2026", "valor": "NaN"},
    {"data": "01/08/2026", "valor": "inf"},
    {"data": "01/08/2026", "valor": None},
    {"data": "01/08/2026", "valor": True},
    {"data": "01/08/2026"},
])
def test_invalid_batch_rejected_whole(bad):
    with pytest.raises(ValueError):
        fetch(11, [{"data": "31/07/2026", "valor": "0.04"}, bad])


def test_snapshot_missing_not_zero():
    with patch("urllib.request.urlopen", side_effect=OSError("offline")):
        snapshot = BacenSgsMiner().get_macro_snapshot()
    assert snapshot["selic_daily"]["status"] == "unavailable"
    assert snapshot["selic_daily"]["valor"] is None


@pytest.mark.parametrize("dates", [["02/08/2026", "01/08/2026"], ["01/08/2026", "01/08/2026"]])
def test_order_and_duplicates_rejected(dates):
    with pytest.raises(ValueError):
        fetch(11, [{"data": date, "valor": "0.04"} for date in dates])


@pytest.mark.parametrize("code", [11, 12])
def test_only_daily_series_compound_at_252(code):
    df, _ = fetch(code, [{"data": "01/08/2026", "valor": "0.04"}])
    assert df["taxa_anual_estimada"].iloc[0] == pytest.approx(((1.0004) ** 252 - 1) * 100)
    assert "not_forecast" in df.attrs["annualization_method"]


@pytest.mark.parametrize("rows", [[], {}, [{"data": "01/08/2026", "valor": "0.04", "extra": 1}]])
def test_empty_or_malformed_response_fails(rows):
    with pytest.raises(ValueError):
        fetch(11, rows)


@pytest.mark.parametrize("kwargs", [{"series_code": 999}, {"series_code": 11, "last_n": 21},
    {"series_code": 11, "last_n": 0}, {"series_code": 11, "last_n": True},
    {"series_code": 11, "last_n": 1, "start_date": "01/08/2026"}])
def test_query_never_silently_truncated(kwargs):
    with patch("urllib.request.urlopen") as opener:
        with pytest.raises(ValueError):
            BacenSgsMiner().fetch_series(**kwargs)
        opener.assert_not_called()


def test_snapshot_keeps_monthly_rate_separate():
    response = MagicMock()
    response.read.return_value = b'[{"data":"01/08/2026","valor":"0.04"}]'
    with patch("urllib.request.urlopen") as opener:
        opener.return_value.__enter__.return_value = response
        snapshot = BacenSgsMiner().get_macro_snapshot()
    assert snapshot["ipca_monthly"]["taxa_anual"] is None
    assert snapshot["ipca_monthly"]["unit"] == "% monthly"
    assert snapshot["selic_meta"]["taxa_anual"] == 0.04
    assert snapshot["ipca_monthly"]["provenance"]["point_in_time_verified"] is False
