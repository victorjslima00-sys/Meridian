import logging
import math
from typing import Any, Optional

logger = logging.getLogger(__name__)

_UNSET = object()


def validate_reference_equity(reference_equity: Any) -> float:
    """
    Valida a referência canônica de equity (NEXUS-005-C1).
    Domains:
      reference_equity > 0 e finito (não None, não NaN, não +Inf, não -Inf, não <= 0).
    Se inválido, falha closed levantando ValueError.
    """
    if reference_equity is None:
        raise ValueError("Reference equity is unavailable (None)")
    try:
        val = float(reference_equity)
    except (TypeError, ValueError):
        raise ValueError(f"Reference equity is not a valid number: {reference_equity}")
    if math.isnan(val) or math.isinf(val):
        raise ValueError(f"Reference equity is non-finite: {val}")
    if val <= 0:
        raise ValueError(f"Reference equity must be strictly positive (> 0), got: {val}")
    return val


def calculate_position_size(
    capital_cash: float,
    open_positions_capital: float = 0.0,
    kelly_fraction: float = 0.25,
    max_positions: int = 3,
    current_open_count: int = 0,
    max_position_fraction: float = 0.10,
    reference_equity: Any = _UNSET,
) -> float:
    """
    Calcula o tamanho da posição alocando capital livre (NEXUS-005-C1).
    Fórmula canônica:
        kelly_cap = reference_equity * kelly_fraction
        concentration_cap = reference_equity * max_position_fraction
        allocated_capital = min(kelly_cap, concentration_cap, saldo_operavel)

    Required domains:
        reference_equity > 0 and finite
        0 < kelly_fraction <= 1
        0 < max_position_fraction <= 1
        saldo_operavel >= 0 and finite
        max_positions >= 1

    Args:
        capital_cash: Capital líquido disponível para investir (saldo_operavel).
        open_positions_capital: Total de capital já alocado no momento.
        kelly_fraction: Fração do total que se deseja alocar por trade (ex: 0.25).
                        Deve estar em (0, 1].
        max_positions: Limite máximo de posições concorrentes (>= 1).
        current_open_count: Número de posições abertas no momento (>= 0).
        max_position_fraction: Fração máxima de concentração por posição (ex: 0.10).
                               Deve estar em (0, 1].
        reference_equity: Referência canônica de equity (saldo_livre + mtm ativo).
                          Se omitido (_UNSET), calcula capital_cash + open_positions_capital.

    Returns:
        Capital em Reais (R$) a ser alocado para o novo trade.
    """
    # Guard-rails: validação estrita de configuração (FAIL CLOSED - sem fallback 0.25)
    if not isinstance(kelly_fraction, (int, float)) or math.isnan(kelly_fraction) or math.isinf(kelly_fraction):
        raise ValueError(f"kelly_fraction must be a finite number, got: {kelly_fraction}")
    if not (0 < kelly_fraction <= 1.0):
        raise ValueError(f"Invalid kelly_fraction: {kelly_fraction}. Must be in domain (0, 1].")

    if not isinstance(max_position_fraction, (int, float)) or math.isnan(max_position_fraction) or math.isinf(max_position_fraction):
        raise ValueError(f"max_position_fraction must be a finite number, got: {max_position_fraction}")
    if not (0 < max_position_fraction <= 1.0):
        raise ValueError(f"Invalid max_position_fraction: {max_position_fraction}. Must be in domain (0, 1].")

    if not isinstance(max_positions, int) or max_positions < 1:
        raise ValueError(f"Invalid max_positions: {max_positions}. Must be an integer >= 1.")

    if not isinstance(current_open_count, int) or current_open_count < 0:
        raise ValueError(f"Invalid current_open_count: {current_open_count}. Must be an integer >= 0.")

    if current_open_count >= max_positions:
        logger.info("Limite de max_positions (%d) atingido. Rejeitando alocação.", max_positions)
        return 0.0

    # Determinar e validar reference_equity
    if reference_equity is not _UNSET:
        ref_eq = validate_reference_equity(reference_equity)
    else:
        if not math.isfinite(capital_cash) or not math.isfinite(open_positions_capital):
            raise ValueError(
                f"Non-finite equity components: cash={capital_cash}, positions={open_positions_capital}"
            )
        computed_eq = capital_cash + open_positions_capital
        ref_eq = validate_reference_equity(computed_eq)

    # Validar saldo_operavel (capital_cash)
    if not isinstance(capital_cash, (int, float)) or math.isnan(capital_cash) or math.isinf(capital_cash):
        raise ValueError(f"capital_cash (saldo_operavel) must be a finite number, got: {capital_cash}")
    if capital_cash < 0:
        raise ValueError(f"capital_cash (saldo_operavel) cannot be negative, got: {capital_cash}")
    if capital_cash == 0:
        return 0.0

    kelly_cap = ref_eq * kelly_fraction
    concentration_cap = ref_eq * max_position_fraction
    allocated_capital = min(kelly_cap, concentration_cap, capital_cash)

    if allocated_capital <= 0:
        return 0.0

    return round(allocated_capital, 4)

