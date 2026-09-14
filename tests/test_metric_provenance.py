"""Entirely synthetic evidence, values and approvals; no financial data claims."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from trading_bot.data.metric_provenance import MetricProvenanceAgent, MetricRecord, metric_digest


@pytest.fixture
def sample(tmp_path):
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    source = tmp_path / "synthetic.txt"
    source.write_bytes(b"synthetic fixture only")
    payload = dict(metric_name="synthetic_metric", value=1.0, unit="synthetic_units", source_ref=source.name,
                   source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                   observed_at=now-timedelta(hours=3), collected_at=now-timedelta(hours=2),
                   computed_at=now-timedelta(hours=1), owner="test_producer", method_version="fixture_v1")
    registry = tmp_path / "trusted_approvals.json"
    def approve(data=payload, reviewer="test_reviewer"):
        record = MetricRecord.model_validate(data)
        approval = dict(metric_name=record.metric_name,
                        metric_sha256=metric_digest(record),
                        reviewed_by=reviewer, reviewed_at=now.isoformat(), status="approved")
        registry.write_text(json.dumps(dict(version=1, approvals=[approval])), encoding="utf-8")
    return MetricProvenanceAgent(tmp_path, registry), payload, now, source, registry, approve


def test_only_separate_exact_approval_publishes(sample):
    agent, payload, now, _, _, approve = sample
    assert agent.evaluate(payload, now=now)["value"] is None
    approve()
    result = agent.evaluate(payload, now=now)
    assert result["value"] == 1.0
    assert result["verification_status"] == "verified"


def test_producer_verified_flag_is_not_approval(sample):
    agent, payload, now, *_ = sample
    result = agent.evaluate({**payload, "verification_status": "verified"}, now=now)
    assert result["value"] is None
    assert result["reason"] == "independent_approval_required"


@pytest.mark.parametrize("field,value", [("metric_name", "other_metric"), ("value", 2.0), ("unit", "other"), ("method_version", "v2"), ("owner", "other")])
def test_approval_does_not_transfer_to_changed_metric(sample, field, value):
    agent, payload, now, _, _, approve = sample
    approve()
    assert agent.evaluate({**payload, field: value}, now=now)["value"] is None


def test_approval_does_not_transfer_between_different_metric_names(sample):
    agent, payload, now, _, registry, approve = sample
    approve()
    # Attempt to evaluate another metric (e.g. avg_win) using approval granted for synthetic_metric
    different_metric = {**payload, "metric_name": "different_metric"}
    res = agent.evaluate(different_metric, now=now)
    assert res["verification_status"] == "unavailable"
    assert res["reason"] == "independent_approval_required"
    assert res["value"] is None


def test_changed_and_missing_evidence_block(sample):
    agent, payload, now, source, _, approve = sample
    approve()
    source.write_bytes(b"tampered fixture")
    assert agent.evaluate(payload, now=now)["value"] is None
    source.unlink()
    assert agent.evaluate(payload, now=now)["value"] is None


@pytest.mark.parametrize("ref", ["../outside.txt", "/outside.txt", "https://example.org/source"])
def test_nonlocal_or_escaping_source_blocks(sample, ref):
    agent, payload, now, *_ = sample
    assert agent.evaluate({**payload, "source_ref": ref}, now=now)["value"] is None


@pytest.mark.parametrize("change", ["naive", "future", "order", "nan", "missing", "extra", "empty_metric_name"])
def test_invalid_contract_blocks(sample, change):
    agent, payload, now, *_ = sample
    data = dict(payload)
    if change == "naive": data["observed_at"] = now.replace(tzinfo=None)
    elif change == "future": data["computed_at"] = now + timedelta(days=1)
    elif change == "order": data["observed_at"] = now
    elif change == "nan": data["value"] = float("nan")
    elif change == "missing": data.pop("source_sha256")
    elif change == "empty_metric_name": data["metric_name"] = "  "
    else: data["approval"] = True
    assert agent.evaluate(data, now=now)["value"] is None


def test_self_approval_and_duplicate_approval_block(sample):
    agent, payload, now, _, registry, approve = sample
    approve(reviewer="test_producer")
    assert agent.evaluate(payload, now=now)["value"] is None
    approve()
    data = json.loads(registry.read_text())
    data["approvals"] *= 2
    registry.write_text(json.dumps(data))
    assert agent.evaluate(payload, now=now)["value"] is None
