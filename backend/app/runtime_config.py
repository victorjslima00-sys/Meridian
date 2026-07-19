"""Validated runtime settings shared by the API and autonomous workers."""
from dataclasses import dataclass

from trading_bot.core.config import AppConfig


_ALLOWED_EXECUTION_MODES = {"manual", "semi_auto", "full_auto"}
_ALLOWED_LLM_FAILURE_POLICIES = {"hold", "technical_fallback"}


@dataclass(frozen=True)
class RuntimeConfig:
    execution_mode: str
    kelly_fraction: float
    max_positions: int
    max_position_fraction: float
    llm_failure_policy: str

    @classmethod
    def load(
        cls,
        settings_path: str = "config/settings.yaml",
        universe_path: str = "config/universe.yaml",
    ) -> "RuntimeConfig":
        cfg = AppConfig.load(settings_path, universe_path)
        execution_mode = str(cfg.get("execution", "mode", default="manual"))
        if execution_mode not in _ALLOWED_EXECUTION_MODES:
            raise ValueError(
                "execution.mode inválido; use manual, semi_auto ou full_auto"
            )

        kelly_fraction = float(cfg.get("risk", "kelly_fraction", default=0.25))
        max_positions = int(cfg.get("risk", "max_positions", default=3))
        max_position_fraction = float(
            cfg.get("risk", "max_position_fraction", default=0.10)
        )
        failure_policy = str(cfg.get("llm", "failure_policy", default="hold"))

        if not 0 < kelly_fraction <= 1:
            raise ValueError("risk.kelly_fraction deve estar em (0, 1]")
        if max_positions < 1:
            raise ValueError("risk.max_positions deve ser >= 1")
        if not 0 < max_position_fraction <= 1:
            raise ValueError("risk.max_position_fraction deve estar em (0, 1]")
        if failure_policy not in _ALLOWED_LLM_FAILURE_POLICIES:
            raise ValueError(
                "llm.failure_policy inválida; use hold ou technical_fallback"
            )

        return cls(
            execution_mode=execution_mode,
            kelly_fraction=kelly_fraction,
            max_positions=max_positions,
            max_position_fraction=max_position_fraction,
            llm_failure_policy=failure_policy,
        )

    @property
    def autonomous_entries_enabled(self) -> bool:
        return self.execution_mode == "full_auto"
