import math
from typing import Any, Optional, Tuple, Dict

# Canonical monetary epsilon (BRL)
# Standard Brazilian Real precision is centavos (0.01 BRL).
# 1e-4 BRL (0.0001 BRL) is two decimal orders of magnitude smaller than 1 centavo,
# completely preventing capital leakage/arbitrage while accommodating IEEE 754 floating-point noise.
MONETARY_EPSILON: float = 1e-4


class AccountingIntegrityError(RuntimeError):
    """Base exception for accounting and financial domain integrity violations."""
    pass


class PortfolioIntegrityError(AccountingIntegrityError):
    """Integrity failure in portfolio row singleton or balance invariants."""
    pass


def validate_monetary_value(
    value: Any,
    name: str,
    *,
    allow_zero: bool = True,
    allow_none: bool = False,
) -> Optional[float]:
    """Strictly validates that a monetary value belongs to the canonical financial domain.

    Rules:
    - None is rejected unless allow_none is True.
    - bool is strictly rejected (e.g. True/False/numpy.bool_).
    - Must be a real numeric type (int or float).
    - Must be finite (NaN, +Inf, -Inf are rejected).
    - If allow_zero is True: value must be >= 0.0.
    - If allow_zero is False: value must be > 0.0.
    """
    if value is None:
        if allow_none:
            return None
        raise AccountingIntegrityError(f"{name} cannot be None")

    if isinstance(value, bool) or type(value).__name__ in ("bool", "bool_"):
        raise AccountingIntegrityError(f"{name} cannot be a boolean (got {value!r})")

    if not isinstance(value, (int, float)):
        raise AccountingIntegrityError(
            f"{name} must be numeric, got {type(value).__name__} ({value!r})"
        )

    try:
        f_val = float(value)
    except (TypeError, ValueError) as e:
        raise AccountingIntegrityError(f"{name} cannot be converted to float: {e}")

    if not math.isfinite(f_val):
        raise AccountingIntegrityError(f"{name} must be finite (got {value})")

    if allow_zero:
        if f_val < 0.0:
            raise AccountingIntegrityError(f"{name} cannot be negative (got {f_val})")
    else:
        if f_val <= 0.0:
            raise AccountingIntegrityError(f"{name} must be strictly positive (got {f_val})")

    return f_val


def validate_portfolio_fields(
    patrimonio_total: Any,
    saldo_disponivel: Any,
    em_posicoes: Any,
    margem_operavel: Any = None,
) -> Tuple[float, float, float, Optional[float], float, float]:
    """Validates portfolio balances against canonical financial invariants.

    Returns:
        (patrimonio_total, saldo_disponivel, em_posicoes, margem_operavel, saldo_livre, saldo_operavel)
    Raises:
        PortfolioIntegrityError on invariant violation.
    """
    try:
        pat = validate_monetary_value(patrimonio_total, "patrimonio_total", allow_zero=True)
        disp = validate_monetary_value(saldo_disponivel, "saldo_disponivel", allow_zero=True)
        pos = validate_monetary_value(em_posicoes, "em_posicoes", allow_zero=True)
        margem = validate_monetary_value(margem_operavel, "margem_operavel", allow_zero=True, allow_none=True)
    except AccountingIntegrityError as e:
        raise PortfolioIntegrityError(f"Corrupt portfolio field: {e}") from e

    # Invariant: saldo_livre = saldo_disponivel - em_posicoes >= 0
    delta = disp - pos
    if delta < -MONETARY_EPSILON:
        raise PortfolioIntegrityError(
            f"Accounting invariant failure: saldo_disponivel ({disp}) < em_posicoes ({pos}) by {abs(delta):.6f}"
        )
    saldo_livre = 0.0 if abs(delta) <= MONETARY_EPSILON else round(delta, 4)

    if margem is None:
        saldo_operavel = saldo_livre
    else:
        saldo_operavel = round(min(saldo_livre, max(0.0, margem - pos)), 4)

    return pat, disp, pos, margem, saldo_livre, saldo_operavel


def validate_and_compute_portfolio_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """Validates raw portfolio row dict and derives canonical saldo_livre and saldo_operavel."""
    for k in ("patrimonio_total", "saldo_disponivel", "em_posicoes"):
        if k not in row or row[k] is None:
            raise PortfolioIntegrityError(f"Missing required portfolio column or NULL value: {k}")

    pat, disp, pos, margem, saldo_livre, saldo_operavel = validate_portfolio_fields(
        row["patrimonio_total"],
        row["saldo_disponivel"],
        row["em_posicoes"],
        row.get("margem_operavel"),
    )

    result = dict(row)
    result["patrimonio_total"] = pat
    result["saldo_disponivel"] = disp
    result["em_posicoes"] = pos
    result["margem_operavel"] = margem
    result["saldo_livre"] = saldo_livre
    result["saldo_operavel"] = saldo_operavel
    return result


def validate_trade_accounting_fields(
    shares: Any,
    price: Any,
    *,
    name_shares: str = "shares",
    name_price: str = "price",
) -> Tuple[float, float]:
    """Validates trade execution/accounting numeric inputs."""
    s = validate_monetary_value(shares, name_shares, allow_zero=False)
    p = validate_monetary_value(price, name_price, allow_zero=False)
    return s, p


def compute_exit_accounting(
    saldo_disponivel: float,
    em_posicoes: float,
    shares: float,
    entry_price: float,
    exit_price: float,
    side: str,
) -> Tuple[float, float, float, float]:
    """Computes exit accounting and enforces non-deficit invariants without silent clamping.

    Returns:
        (new_saldo_disponivel, new_em_posicoes, return_value, pnl_pct)
    Raises:
        AccountingIntegrityError if remaining position capital is negative or invariant fails.
    """
    s, entry_p = validate_trade_accounting_fields(
        shares, entry_price, name_shares="shares", name_price="entry_price"
    )
    _, exit_p = validate_trade_accounting_fields(
        shares, exit_price, name_shares="shares", name_price="exit_price"
    )
    disp = validate_monetary_value(saldo_disponivel, "saldo_disponivel", allow_zero=True)
    pos = validate_monetary_value(em_posicoes, "em_posicoes", allow_zero=True)

    original_allocation = round(s * entry_p, 4)
    gross_value = round(s * exit_p, 4)
    return_value = gross_value

    remaining = pos - original_allocation
    if remaining < -MONETARY_EPSILON:
        raise AccountingIntegrityError(
            f"Accounting invariant failure on exit: em_posicoes ({pos}) < original_allocation ({original_allocation}) by {abs(remaining):.6f}"
        )
    elif abs(remaining) <= MONETARY_EPSILON:
        new_em_pos = 0.0
    else:
        new_em_pos = round(remaining, 4)

    new_disp = round(disp - original_allocation + return_value, 4)
    if new_disp < -MONETARY_EPSILON:
        raise AccountingIntegrityError(
            f"Accounting invariant failure on exit: resulting saldo_disponivel ({new_disp}) < 0"
        )
    elif abs(new_disp) <= MONETARY_EPSILON:
        new_disp = 0.0

    if side == "BUY":
        pnl_pct = float(((exit_p - entry_p) / entry_p) * 100.0)
    elif side == "SELL":
        pnl_pct = float(((entry_p - exit_p) / entry_p) * 100.0)
    else:
        raise AccountingIntegrityError(f"Invalid trade side: {side}")

    return new_disp, new_em_pos, return_value, pnl_pct
