import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


def is_bool_value(val: Any) -> bool:
    """Return True if val is a boolean (Python bool or numpy bool_)."""
    if isinstance(val, bool):
        return True
    if type(val).__name__ in ("bool", "bool_"):
        return True
    try:
        import numpy as np
        if isinstance(val, (np.bool_, bool)):
            return True
    except ImportError:
        pass
    return False


def validate_reference_equity(reference_equity: Any) -> float:
    """
    Valida a referência canônica de equity (NEXUS-005-C1 / R1).
    Domains:
      reference_equity > 0 e finito (não None, não bool, não NaN, não +Inf, não -Inf, não <= 0).
    Se inválido, falha closed levantando ValueError.
    """
    if reference_equity is None:
        raise ValueError("Reference equity is unavailable (None)")
    if is_bool_value(reference_equity):
        raise ValueError(f"Reference equity cannot be a boolean (got {reference_equity!r})")
    if not isinstance(reference_equity, (int, float)):
        try:
            import numpy as np
            if not isinstance(reference_equity, (int, float, np.integer, np.floating)):
                raise ValueError(
                    f"Reference equity must be numeric, got: {type(reference_equity).__name__} ({reference_equity!r})"
                )
        except ImportError:
            raise ValueError(
                f"Reference equity must be numeric, got: {type(reference_equity).__name__} ({reference_equity!r})"
            )
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
    *,
    reference_equity: Any,
) -> float:
    """
    Calcula o tamanho da posição alocando capital livre (NEXUS-005-C1 / R1).
    Fórmula canônica:
        kelly_cap = reference_equity * kelly_fraction
        concentration_cap = reference_equity * max_position_fraction
        allocated_capital = min(kelly_cap, concentration_cap, saldo_operavel)

    Required domains:
        reference_equity > 0 and finite (REQUIRED, explicit, no bool)
        0 < kelly_fraction <= 1 (finite, no bool)
        0 < max_position_fraction <= 1 (finite, no bool)
        saldo_operavel >= 0 and finite (no bool)
        max_positions >= 1 (integer, no bool)
        current_open_count >= 0 (integer, no bool)

    Args:
        capital_cash: Capital líquido disponível para investir (saldo_operavel).
        open_positions_capital: Total de capital já alocado no momento (opcional).
        kelly_fraction: Fração do total que se deseja alocar por trade (ex: 0.25).
                        Deve estar em (0, 1].
        max_positions: Limite máximo de posições concorrentes (>= 1).
        current_open_count: Número de posições abertas no momento (>= 0).
        max_position_fraction: Fração máxima de concentração por posição (ex: 0.10).
                               Deve estar em (0, 1].
        reference_equity: Referência canônica de equity (saldo_livre + mtm ativo).
                          OBRIGATÓRIO. Sem fallback implícito.

    Returns:
        Capital em Reais (R$) a ser alocado para o novo trade.
    """
    # 1. reference_equity (REQUIRED - FAIL CLOSED - NO BOOL - NO FALLBACK)
    ref_eq = validate_reference_equity(reference_equity)

    # 2. kelly_fraction
    if is_bool_value(kelly_fraction):
        raise ValueError(f"kelly_fraction cannot be a boolean (got {kelly_fraction!r})")
    if not isinstance(kelly_fraction, (int, float)):
        try:
            import numpy as np
            if not isinstance(kelly_fraction, (int, float, np.floating)):
                raise ValueError(f"kelly_fraction must be numeric, got: {type(kelly_fraction).__name__} ({kelly_fraction!r})")
        except ImportError:
            raise ValueError(f"kelly_fraction must be numeric, got: {type(kelly_fraction).__name__} ({kelly_fraction!r})")
    if math.isnan(kelly_fraction) or math.isinf(kelly_fraction):
        raise ValueError(f"kelly_fraction must be a finite number, got: {kelly_fraction}")
    if not (0 < kelly_fraction <= 1.0):
        raise ValueError(f"Invalid kelly_fraction: {kelly_fraction}. Must be in domain (0, 1].")

    # 3. max_position_fraction
    if is_bool_value(max_position_fraction):
        raise ValueError(f"max_position_fraction cannot be a boolean (got {max_position_fraction!r})")
    if not isinstance(max_position_fraction, (int, float)):
        try:
            import numpy as np
            if not isinstance(max_position_fraction, (int, float, np.floating)):
                raise ValueError(f"max_position_fraction must be numeric, got: {type(max_position_fraction).__name__} ({max_position_fraction!r})")
        except ImportError:
            raise ValueError(f"max_position_fraction must be numeric, got: {type(max_position_fraction).__name__} ({max_position_fraction!r})")
    if math.isnan(max_position_fraction) or math.isinf(max_position_fraction):
        raise ValueError(f"max_position_fraction must be a finite number, got: {max_position_fraction}")
    if not (0 < max_position_fraction <= 1.0):
        raise ValueError(f"Invalid max_position_fraction: {max_position_fraction}. Must be in domain (0, 1].")

    # 4. max_positions
    if is_bool_value(max_positions):
        raise ValueError(f"max_positions cannot be a boolean (got {max_positions!r})")
    if not isinstance(max_positions, int):
        try:
            import numpy as np
            if not isinstance(max_positions, (int, np.integer)):
                raise ValueError(f"Invalid max_positions: {max_positions}. Must be an integer >= 1.")
        except ImportError:
            raise ValueError(f"Invalid max_positions: {max_positions}. Must be an integer >= 1.")
    if max_positions < 1:
        raise ValueError(f"Invalid max_positions: {max_positions}. Must be an integer >= 1.")

    # 5. current_open_count
    if is_bool_value(current_open_count):
        raise ValueError(f"current_open_count cannot be a boolean (got {current_open_count!r})")
    if not isinstance(current_open_count, int):
        try:
            import numpy as np
            if not isinstance(current_open_count, (int, np.integer)):
                raise ValueError(f"Invalid current_open_count: {current_open_count}. Must be an integer >= 0.")
        except ImportError:
            raise ValueError(f"Invalid current_open_count: {current_open_count}. Must be an integer >= 0.")
    if current_open_count < 0:
        raise ValueError(f"Invalid current_open_count: {current_open_count}. Must be an integer >= 0.")

    # 6. capital_cash (saldo_operavel)
    if is_bool_value(capital_cash):
        raise ValueError(f"capital_cash (saldo_operavel) cannot be a boolean (got {capital_cash!r})")
    if not isinstance(capital_cash, (int, float)):
        try:
            import numpy as np
            if not isinstance(capital_cash, (int, float, np.integer, np.floating)):
                raise ValueError(f"capital_cash (saldo_operavel) must be numeric, got: {type(capital_cash).__name__} ({capital_cash!r})")
        except ImportError:
            raise ValueError(f"capital_cash (saldo_operavel) must be numeric, got: {type(capital_cash).__name__} ({capital_cash!r})")
    if math.isnan(capital_cash) or math.isinf(capital_cash):
        raise ValueError(f"capital_cash (saldo_operavel) must be a finite number, got: {capital_cash}")
    if capital_cash < 0:
        raise ValueError(f"capital_cash (saldo_operavel) cannot be negative, got: {capital_cash}")

    # 7. open_positions_capital (if provided)
    if is_bool_value(open_positions_capital):
        raise ValueError(f"open_positions_capital cannot be a boolean (got {open_positions_capital!r})")
    if not isinstance(open_positions_capital, (int, float)):
        try:
            import numpy as np
            if not isinstance(open_positions_capital, (int, float, np.integer, np.floating)):
                raise ValueError(f"open_positions_capital must be numeric, got: {type(open_positions_capital).__name__} ({open_positions_capital!r})")
        except ImportError:
            raise ValueError(f"open_positions_capital must be numeric, got: {type(open_positions_capital).__name__} ({open_positions_capital!r})")
    if math.isnan(open_positions_capital) or math.isinf(open_positions_capital) or open_positions_capital < 0:
        raise ValueError(f"open_positions_capital must be a finite non-negative number, got: {open_positions_capital}")

    if current_open_count >= max_positions:
        logger.info("Limite de max_positions (%d) atingido. Rejeitando alocação.", max_positions)
        return 0.0

    if capital_cash == 0:
        return 0.0

    kelly_cap = ref_eq * float(kelly_fraction)
    concentration_cap = ref_eq * float(max_position_fraction)
    allocated_capital = min(kelly_cap, concentration_cap, float(capital_cash))

    if allocated_capital <= 0:
        return 0.0

    res = round(allocated_capital, 4)
    if res > float(capital_cash):
        res = float(capital_cash)
    return round(res, 4)
