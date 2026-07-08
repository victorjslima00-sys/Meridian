import logging

logger = logging.getLogger(__name__)


def calculate_position_size(
    capital_cash: float,
    open_positions_capital: float,
    kelly_fraction: float,
    max_positions: int,
    current_open_count: int,
) -> float:
    """
    Calcula o tamanho da posição alocando capital livre.
    Usa um Kelly fracionado. Se estourar o max_positions, retorna 0.

    Args:
        capital_cash: Capital líquido disponível para investir.
        open_positions_capital: Total de capital já alocado no momento.
        kelly_fraction: Fração do total que se deseja alocar por trade (ex: 0.25).
                        Deve estar em (0, 1].
        max_positions: Limite máximo de posições concorrentes.
        current_open_count: Número de posições abertas no momento.

    Returns:
        Capital em Reais (R$) a ser alocado para o novo trade.
    """
    # Guard-rail: parâmetros inválidos
    if not (0 < kelly_fraction <= 1.0):
        logger.warning("kelly_fraction inválido: %.4f. Usando 0.25 como fallback.", kelly_fraction)
        kelly_fraction = 0.25

    if capital_cash <= 0:
        return 0.0

    if current_open_count >= max_positions:
        logger.info("Limite de max_positions (%d) atingido. Rejeitando alocação.", max_positions)
        return 0.0

    total_equity = capital_cash + open_positions_capital
    allocation = total_equity * kelly_fraction

    # Se a alocação proposta for maior do que o cash disponível,
    # investe apenas o cash que sobrou (nunca alavancar).
    final_allocation = min(allocation, capital_cash)

    if final_allocation <= 0:
        return 0.0

    return final_allocation
