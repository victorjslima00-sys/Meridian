"""Production strategy identity contracts (NEXUS-003-R2).

Centralizes the single source of truth for strategy identification across
candidate generation, candidate manifest validation, execution-time approval
verification, and MarketAnalyst signal emission.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Set

from trading_bot.core.config import AppConfig

SUPPORTED_STRATEGIES: Set[str] = {"donchian_breakout"}
DEFAULT_STRATEGY_ID: str = "donchian_breakout"


def get_active_strategy_id(settings_path: Optional[Path | str] = None) -> str:
    """Read configured strategy identity, failing closed if unsupported.

    Fails closed:
    - If explicit settings_path is provided but does not exist or parse.
    - If 'signals.strategy' key is missing, empty, or not a string.
    - If the configured strategy is not members of SUPPORTED_STRATEGIES.
    """
    if settings_path is not None:
        p = Path(settings_path)
        if not p.is_file():
            raise FileNotFoundError(f"settings_file_not_found: {p}")
        cfg = AppConfig.load(settings_path=str(p))
    else:
        cfg = AppConfig.load()

    strat = cfg.get("signals", "strategy")
    if not strat or not isinstance(strat, str) or not strat.strip():
        raise ValueError("missing_or_empty_strategy_id")

    clean_strat = strat.strip()
    if clean_strat not in SUPPORTED_STRATEGIES:
        raise ValueError(
            f"unsupported_strategy: '{clean_strat}' is not supported. "
            f"Supported strategies: {sorted(SUPPORTED_STRATEGIES)}"
        )
    return clean_strat
