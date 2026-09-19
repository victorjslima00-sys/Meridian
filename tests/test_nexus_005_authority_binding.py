"""Persisted authority and trusted context integration tests for NEXUS-005-A."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from backend.app.agents.contracts import (
    ApprovedExecutionIntent, TypedSignal, compute_signal_id, compute_intent_id,
    compute_decision_id, SIGNAL_CONTRACT_VERSION, RISK_CONTRACT_VERSION,
    INTENT_CONTRACT_VERSION,
)
from backend.app.agents.executor import ExecutorAgent
from backend.app.agents.market_analyst import MarketAnalyst
from backend.app.agents.risk_manager import RiskManager
from tests.conftest import make_test_evidenced_quote
from trading_bot.data import approval
from trading_bot.data.approval_candidate import build_candidate_bundle

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def authority(tmp_path):
    settings = tmp_path / "settings.yaml"
    settings.write_bytes((ROOT / "config/settings.yaml").read_bytes())
    dates = pd.bdate_range("2024-01-02", periods=250)
    rng = np.random.default_rng(0)
    price, closes = 85.0, []
    for _ in range(249):
        price += 0.015 + rng.normal(0, 0.35)
        closes.append(price)
    closes.append(max(closes[-20:]) * 1.02)
    frame = pd.DataFrame({"date": dates, "close": closes,
                          "open": [c * 0.999 for c in closes],
                          "high": [c * 1.006 if i < 249 else c * 1.001
                                   for i, c in enumerate(closes)],
                          "low": [c * 0.994 for c in closes],
                          "volume": [1000] * 249 + [2500]})
    manifest = build_candidate_bundle(
        ticker="PETR4.SA", output_dir=tmp_path / "candidate",
        project_root=tmp_path, settings_path=settings, df=frame,
    )
    fields = set(approval.Approval.model_fields) - {"reviewed_by", "review_notes", "status"}
    record = approval.Approval(**{k: getattr(manifest, k) for k in fields},
                               reviewed_by="isolated test fixture",
                               review_notes="Synthetic evidence; not a production approval")
    registry = tmp_path / "registry.json"
    registry.write_text(approval.Registry(version=1, approvals=[record]).model_dump_json())
    context = {"approval_context": {"registry_path": registry,
               "project_root": tmp_path, "settings_path": settings}}
    assert approval.require_dataset_approval_by_digest(
        record.dataset_sha256, **context["approval_context"]
    ) == record
    payload = {"ticker": record.ticker, "side": "BUY", "price": 30.0,
               "target_price": 33.0, "stop_loss": 28.5, "reason": "fixture",
               "generated_at": datetime.now(timezone.utc), "dataset_approved": True,
               **{k: getattr(record, k) for k in
                  ("dataset_sha256", "candidate_id", "strategy_id", "intended_use")}}
    return SimpleNamespace(record=record, context=context, payload=payload,
                           frame=frame, registry=registry, root=tmp_path)


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_exact_authority(authority, side):
    payload = dict(authority.payload, side=side)
    if side == "SELL":
        payload.update(target_price=28.5, stop_loss=33.0)
    signal = TypedSignal.model_validate(payload, context=authority.context)
    for key in ("dataset_sha256", "ticker", "strategy_id", "candidate_id", "intended_use"):
        assert getattr(signal, key) == getattr(authority.record, key)


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("field,value", [
    ("ticker", "VALE3.SA"), ("ticker", "PETR4"), ("strategy_id", "other"),
    ("strategy_id", None), ("strategy_id", ""), ("strategy_id", "  "),
    ("candidate_id", "f" * 64), ("candidate_id", None),
    ("candidate_id", "F" * 64), ("candidate_id", "abc"),
    ("intended_use", "LIVE_TRADING"), ("intended_use", None),
    ("dataset_sha256", None), ("dataset_approved", False),
])
def test_reject_identity(authority, side, field, value):
    payload = dict(authority.payload, side=side)
    if side == "SELL":
        payload.update(target_price=28.5, stop_loss=33.0)
    payload[field] = value
    with pytest.raises(ValidationError):
        TypedSignal.model_validate(payload, context=authority.context)


@pytest.mark.parametrize("context", [None, {"unrelated": "metadata"}])
def test_no_context_does_not_discover_custom_registry(authority, context):
    assert json.loads((ROOT / "config/data_approvals.json").read_text()) == {"version": 1, "approvals": []}
    with pytest.raises(ValidationError):
        TypedSignal.model_validate(authority.payload, context=context)
    with pytest.raises(ValidationError):
        TypedSignal(**authority.payload)


@pytest.mark.parametrize("missing", ["registry_path", "project_root", "settings_path"])
def test_partial_context_rejects_before_lookup(authority, missing):
    custom = dict(authority.context["approval_context"])
    custom.pop(missing)
    with patch.object(approval, "require_dataset_approval_by_digest") as lookup:
        with pytest.raises(ValidationError):
            TypedSignal.model_validate(authority.payload, context={"approval_context": custom})
        lookup.assert_not_called()


@pytest.mark.parametrize("custom", [None, {}, [], "path", False,
    {"registry_path": "r", "project_root": "p", "settings_path": None}])
def test_malformed_context(authority, custom):
    with pytest.raises(ValidationError):
        TypedSignal.model_validate(authority.payload, context={"approval_context": custom})


@pytest.mark.parametrize("key", ["registry_path", "project_root", "settings_path", "approval_context"])
def test_payload_context_injection(authority, key):
    with pytest.raises(ValidationError, match="Extra inputs"):
        TypedSignal.model_validate(dict(authority.payload, **{key: "injection"}),
                                   context=authority.context)


def test_contract_version_evolution():
    assert SIGNAL_CONTRACT_VERSION == "2.0"
    assert INTENT_CONTRACT_VERSION == "2.0"
    assert RISK_CONTRACT_VERSION == "1.0"
    base = dict(ticker="PETR4.SA", side="BUY", price=30.0, target_price=33.0,
                stop_loss=28.5, dataset_sha256="0" * 64,
                generated_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
                strategy_id="donchian_breakout")
    assert compute_signal_id(candidate_id="1" * 64, intended_use="PAPER_TRADING", **base) != \
        compute_signal_id(candidate_id="2" * 64, intended_use="PAPER_TRADING", **base)
    assert compute_signal_id(candidate_id="1" * 64, intended_use="LIVE_TRADING", **base) != \
        compute_signal_id(candidate_id="1" * 64, intended_use="PAPER_TRADING", **base)


def test_signal_id_tamper_detected(authority):
    signal = TypedSignal.model_validate(authority.payload, context=authority.context)
    forged = dict(authority.payload, candidate_id="f" * 64, signal_id=signal.signal_id)
    with pytest.raises(ValidationError):
        TypedSignal.model_validate(forged, context=authority.context)


def test_hold_requires_no_authority(authority):
    hold = TypedSignal.model_validate({
        "ticker": "PETR4.SA", "side": "HOLD", "price": 30.0,
        "target_price": 0.0, "stop_loss": 0.0, "reason": "no edge",
        "generated_at": datetime.now(timezone.utc),
        "dataset_sha256": None, "dataset_approved": False,
        "strategy_id": None, "candidate_id": None, "intended_use": None,
    })
    assert hold.candidate_id is None and hold.dataset_approved is False
    with pytest.raises(ValidationError):
        ApprovedExecutionIntent.model_validate({
            "signal": hold.model_dump(mode="python"),
            "risk_decision": {"signal_id": hold.signal_id, "approved": True,
                              "allocated_capital": 100.0, "target_price": 0.0,
                              "stop_loss": 0.0, "reason": "x",
                              "decision_timestamp": datetime.now(timezone.utc)},
            "execution_quote": make_test_evidenced_quote().model_dump(mode="python"),
        })


def _ibov_uptrend_df():
    return pd.DataFrame({
        "ts": pd.date_range("2023-01-02", periods=260, freq="D").date,
        "c": [120000.0] * 260,
        "sma50": [115000.0] * 260,
    })


async def test_analyst_propagates_exact_authority(authority):
    with patch("backend.app.agents.market_analyst.get_ibov_data",
               return_value=_ibov_uptrend_df()):
        result = await MarketAnalyst("PETR4.SA").analyze_ohlcv(
            authority.frame, **authority.context["approval_context"])
    assert result["side"] == "BUY"
    for key in ("dataset_sha256", "candidate_id", "strategy_id", "intended_use"):
        assert result[key] == getattr(authority.record, key)


async def test_analyst_fails_closed_on_identity_mismatch(authority):
    with patch("backend.app.agents.market_analyst.get_ibov_data",
               return_value=_ibov_uptrend_df()):
        result = await MarketAnalyst("VALE3.SA").analyze_ohlcv(
            authority.frame, **authority.context["approval_context"])
    assert result["side"] == "HOLD"
    assert result["dataset_approved"] is False
    assert "candidate_id" not in result


def test_risk_manager_custom_context(authority, mock_circuit_breaker):
    rm = RiskManager(saldo_livre=100_000.0, reference_equity=100_000.0, validation_context=authority.context)
    decision = rm.evaluate_trade(authority.payload)
    assert decision.approved is True
    assert decision.signal_id == compute_signal_id(
        ticker=authority.record.ticker, side="BUY", price=30.0, target_price=33.0,
        stop_loss=28.5, dataset_sha256=authority.record.dataset_sha256,
        generated_at=authority.payload["generated_at"],
        strategy_id=authority.record.strategy_id,
        candidate_id=authority.record.candidate_id,
        intended_use=authority.record.intended_use,
    )


def test_risk_manager_without_context_rejects(authority, mock_circuit_breaker):
    rm = RiskManager(saldo_livre=100_000.0)
    decision = rm.evaluate_trade(authority.payload)
    assert decision.approved is False


def _isolated_db(path):
    import sqlite3
    conn = sqlite3.connect(str(path))
    conn.execute("""CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT, side TEXT, shares REAL, entry_price REAL, exit_price REAL,
        target_price REAL, stop_loss REAL, entry_date TIMESTAMP, exit_date TIMESTAMP,
        pnl_pct REAL, exit_reason TEXT, ai_rationale TEXT, status TEXT, signal_id TEXT)""")
    conn.execute("""CREATE TABLE portfolio (id INTEGER PRIMARY KEY AUTOINCREMENT,
        patrimonio_total REAL DEFAULT 0.0, saldo_disponivel REAL DEFAULT 0.0,
        em_posicoes REAL DEFAULT 0.0, margem_operavel REAL, updated_at TIMESTAMP)""")
    conn.execute("INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, updated_at) VALUES (2000.0, 2000.0, 0.0, ?)",
                 (datetime.now(timezone.utc).isoformat(),))
    conn.execute("CREATE UNIQUE INDEX idx_trades_strategy_signal_id ON trades(signal_id) WHERE signal_id IS NOT NULL")
    conn.execute("CREATE UNIQUE INDEX idx_trades_single_active ON trades(ticker) WHERE status = 'active'")
    conn.commit()
    conn.close()


def _intent_under(authority):
    signal = TypedSignal.model_validate(authority.payload, context=authority.context)
    from backend.app.agents.contracts import RiskDecision
    risk = RiskDecision(signal_id=signal.signal_id, approved=True, allocated_capital=150.0,
                        target_price=signal.target_price, stop_loss=signal.stop_loss,
                        reason="risk ok", decision_timestamp=datetime.now(timezone.utc))
    quote = make_test_evidenced_quote(ticker="PETR4.SA", price=30.0)
    return ApprovedExecutionIntent.model_validate({
        "signal": signal.model_dump(mode="python"),
        "risk_decision": risk.model_dump(mode="python"),
        "execution_quote": quote.model_dump(mode="python"),
    }, context=authority.context)


def test_intent_binds_authority_and_is_deterministic(authority):
    intent = _intent_under(authority)
    assert intent.candidate_id == authority.record.candidate_id
    assert intent.intended_use == "PAPER_TRADING"
    assert intent.intent_id != compute_intent_id(
        signal_id=intent.signal.signal_id, decision_id=intent.risk_decision.decision_id,
        ticker="PETR4.SA", side="BUY", decision_price=30.0, execution_price=30.0,
        allocated_capital=150.0, target_price=33.0, stop_loss=28.5,
        dataset_sha256=authority.record.dataset_sha256,
        candidate_id="f" * 64, intended_use="PAPER_TRADING",
        quote_ticker="PETR4.SA", quote_source="yfinance", quote_price_kind="bar_close",
        quote_observed_at=intent.execution_quote.observed_at,
        quote_collected_at=intent.execution_quote.collected_at,
        quote_source_sha256=intent.execution_quote.source_sha256,
    )


def _allowing_session():
    return SimpleNamespace(check_authority=lambda *a, **k: (True, "test", None, None))


def test_executor_context_preservation(authority, tmp_path):
    intent = _intent_under(authority)
    db = tmp_path / "exec.db"
    _isolated_db(db)
    allowed = ExecutorAgent(db_path=str(db), session_authority=_allowing_session(),
                            validation_context=authority.context)
    result = allowed.execute_order(intent)
    assert result["status"] != "rejected"
    denied = ExecutorAgent(db_path=str(tmp_path / "exec2.db"), session_authority=_allowing_session())
    assert denied.execute_order(intent)["status"] == "rejected"


def test_nested_model_context_reaches_signal_lookup(authority, monkeypatch):
    intent = _intent_under(authority)
    captured = {}
    real = approval.require_dataset_approval_by_digest

    def spy(digest, **kwargs):
        captured.update(kwargs)
        return real(digest, **kwargs)

    monkeypatch.setattr(approval, "require_dataset_approval_by_digest", spy)
    dump = intent.model_dump(mode="python")
    ApprovedExecutionIntent.model_validate(dump, context=authority.context)
    assert captured == authority.context["approval_context"]



