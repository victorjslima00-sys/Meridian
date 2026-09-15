"""
Schema Pydantic pra resposta do LLM (MarketAnalyst) — CLAUDE.md: "Toda
resposta de LLM e entrada externa validada com Pydantic e invariantes
semânticas (em BUY: stop_loss < preço < target_price)". Substitui a
checagem aritmética solta que existia em risk_manager.py
(if risk <= 0 or reward <= 0) — o schema é agora a única fonte de
verdade pra essa invariante, aplicada ANTES do risk_manager ver o sinal.

Os limites de distância não são números inventados: max_stop_distance_pct
vem de signals.stop_pct em config/settings.yaml (já documentado ali como
"Stop-loss rígido de emergência — Hard Cap", usado pelo motor de sinais
técnico do projeto); max_target_distance_pct é derivado multiplicando
esse mesmo stop_pct pela razão target_atr_mult/stop_atr_mult (3.0/1.5 =
2.0), a mesma razão risco:retorno já calibrada pro motor técnico —
nenhum threshold novo foi inventado.
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def _limites_de_distancia_pct() -> tuple[float, float]:
    """(max_stop_distance_pct, max_target_distance_pct), derivados de
    config/settings.yaml. Lido a cada chamada (não congelado em import)
    para acompanhar mudanças de config sem reiniciar o processo — mesmo
    padrão de RuntimeConfig.load()."""
    from trading_bot.core.config import AppConfig

    cfg = AppConfig.load()
    stop_pct = float(cfg.get("signals", "stop_pct", default=0.04))
    target_mult = float(cfg.get("signals", "target_atr_mult", default=3.0))
    stop_mult = float(cfg.get("signals", "stop_atr_mult", default=1.5))
    razao = (target_mult / stop_mult) if stop_mult > 0 else 2.0
    return stop_pct, stop_pct * razao


class AnalystDecision(BaseModel):
    """Resultado validado de uma análise do MarketAnalyst. `current_price`
    não vem do JSON do LLM — é o preço real de mercado (já conhecido pelo
    caller antes de perguntar ao LLM), passado explicitamente pra permitir
    validar a ordem stop/preço/alvo."""

    signal: Literal["BUY", "SELL", "HOLD"]
    confidence: int = Field(ge=0, le=100)
    target_price: float
    stop_loss: float
    reason: str
    current_price: float

    @model_validator(mode="after")
    def validar_invariantes_de_preco(self) -> "AnalystDecision":
        if self.signal == "HOLD":
            return self

        if self.target_price <= 0 or self.stop_loss <= 0 or self.current_price <= 0:
            raise ValueError(
                f"{self.signal}: target_price, stop_loss e current_price devem "
                f"ser positivos (target={self.target_price}, stop={self.stop_loss}, "
                f"atual={self.current_price})."
            )

        if self.signal == "BUY":
            if not (self.stop_loss < self.current_price < self.target_price):
                raise ValueError(
                    "BUY exige stop_loss < preço_atual < target_price "
                    f"(stop={self.stop_loss}, atual={self.current_price}, "
                    f"target={self.target_price})."
                )
            stop_dist = (self.current_price - self.stop_loss) / self.current_price
            target_dist = (self.target_price - self.current_price) / self.current_price
        else:  # SELL
            if not (self.target_price < self.current_price < self.stop_loss):
                raise ValueError(
                    "SELL exige target_price < preço_atual < stop_loss "
                    f"(target={self.target_price}, atual={self.current_price}, "
                    f"stop={self.stop_loss})."
                )
            stop_dist = (self.stop_loss - self.current_price) / self.current_price
            target_dist = (self.current_price - self.target_price) / self.current_price

        max_stop_distance_pct, max_target_distance_pct = _limites_de_distancia_pct()

        if stop_dist > max_stop_distance_pct:
            raise ValueError(
                f"Stop a {stop_dist:.1%} do preço atual excede o limite de "
                f"{max_stop_distance_pct:.1%} (signals.stop_pct em settings.yaml)."
            )
        if target_dist > max_target_distance_pct:
            raise ValueError(
                f"Alvo a {target_dist:.1%} do preço atual excede o limite de "
                f"{max_target_distance_pct:.1%} (derivado de signals.stop_pct × "
                f"target_atr_mult/stop_atr_mult em settings.yaml)."
            )
        return self

import hashlib
import json
from datetime import datetime, timezone
from pydantic import ConfigDict

class StrategySignal(BaseModel):
    """The smallest strict typed contract necessary for autonomous/strategy-generated signals."""
    model_config = ConfigDict(strict=True, extra="forbid")

    ticker: str = Field(min_length=1)
    signal: Literal["BUY", "SELL"]
    current_price: float = Field(gt=0, allow_inf_nan=False)
    target_price: float = Field(gt=0, allow_inf_nan=False)
    stop_loss: float = Field(gt=0, allow_inf_nan=False)
    confidence: int | None = Field(default=None, ge=0, le=100)
    reason: str = Field(min_length=1)
    generated_at: datetime
    dataset_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    dataset_approved: bool

    @property
    def signal_id(self) -> str:
        payload = {
            "ticker": self.ticker,
            "signal": self.signal,
            "current_price": float(self.current_price),
            "target_price": float(self.target_price),
            "stop_loss": float(self.stop_loss),
            "dataset_sha256": self.dataset_sha256,
            "generated_at": self.generated_at.isoformat(),
        }
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @model_validator(mode="after")
    def validate_invariants(self) -> "StrategySignal":
        if self.generated_at.tzinfo is None or self.generated_at.tzinfo.utcoffset(self.generated_at) is None:
            raise ValueError("generated_at must be timezone-aware")

        if self.signal == "BUY":
            if not (self.stop_loss < self.current_price < self.target_price):
                raise ValueError("BUY requires stop_loss < current_price < target_price")
        else:  # SELL
            if not (self.target_price < self.current_price < self.stop_loss):
                raise ValueError("SELL requires target_price < current_price < stop_loss")

        if not self.dataset_approved:
            raise ValueError("Strategy signal dataset must be approved")
        
        from trading_bot.data.approval import validate_dataset_digest
        try:
            validate_dataset_digest(self.dataset_sha256)
        except Exception as e:
            raise ValueError("Invalid or unapproved dataset_sha256") from e

        return self

class RiskDecision(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    
    signal_id: str
    approved: bool
    reason: str
    allocated_capital: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    target_price: float = Field(gt=0, allow_inf_nan=False)
    stop_loss: float = Field(gt=0, allow_inf_nan=False)
    decision_timestamp: datetime

    @model_validator(mode="after")
    def validate_approval(self) -> "RiskDecision":
        if self.approved and self.allocated_capital is None:
            raise ValueError("allocated_capital must be set if approved")
        return self

    def __getitem__(self, item):
        return getattr(self, item)

class ApprovedExecutionIntent(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    
    signal_id: str
    risk_decision_id: str
    ticker: str
    side: Literal["BUY", "SELL"]
    entry_price: float = Field(gt=0, allow_inf_nan=False)
    allocated_capital: float = Field(gt=0, allow_inf_nan=False)
    target_price: float = Field(gt=0, allow_inf_nan=False)
    stop_loss: float = Field(gt=0, allow_inf_nan=False)
    dataset_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

class ManualExecutionIntent(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    
    ticker: str
    side: Literal["BUY", "SELL"]
    entry_price: float = Field(gt=0, allow_inf_nan=False)
    allocated_capital: float = Field(gt=0, allow_inf_nan=False)
    target_price: float = Field(gt=0, allow_inf_nan=False)
    stop_loss: float = Field(gt=0, allow_inf_nan=False)
    reason: str
