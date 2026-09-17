"""Trusted approval context regression (NEXUS-005-A)."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from backend.app.agents.contracts import TypedSignal


def test_explicit_approval_context_reaches_lookup(tmp_path):
    """Intercept only to observe arguments; never manufacture authority."""
    custom = {
        "registry_path": tmp_path / "registry.json",
        "project_root": tmp_path,
        "settings_path": tmp_path / "settings.yaml",
    }
    payload = {
        "ticker": "PETR4.SA", "side": "BUY", "price": 30.0,
        "target_price": 33.0, "stop_loss": 28.5, "reason": "context diagnostic",
        "generated_at": datetime.now(timezone.utc),
        "dataset_sha256": "0" * 64, "dataset_approved": True,
        "strategy_id": "donchian_breakout",
        "candidate_id": "1" * 64, "intended_use": "PAPER_TRADING",
    }
    with patch(
        "trading_bot.data.approval.require_dataset_approval_by_digest",
        side_effect=ValueError("diagnostic rejection; no registry access"),
    ) as lookup:
        with pytest.raises(ValidationError):
            TypedSignal.model_validate(payload, context={"approval_context": custom})
    lookup.assert_called_once_with("0" * 64, **custom)
