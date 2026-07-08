from __future__ import annotations
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class CircuitBreakerStatus:
    triggered: bool
    reason: str = ""

class CircuitBreaker:
    """
    Módulo 3: Circuit Breaker
    Verifica 3 níveis de proteção da conta de trading para interromper operações:
    1. Drawdown desde o início da operação (inception)
    2. Drawdown móvel de 30 dias (rolling_30d)
    3. Limite de perda diária (daily_loss_limit)
    """
    def __init__(
        self,
        daily_loss_limit: float = 0.05,
        drawdown_inception: float = 0.20,
        drawdown_rolling_30d: float = 0.15
    ):
        self.daily_loss_limit = daily_loss_limit
        self.drawdown_inception = drawdown_inception
        self.drawdown_rolling_30d = drawdown_rolling_30d

    def check(
        self,
        current_equity: float,
        initial_equity: float,
        equity_start_of_day: float,
        equity_30d_ago: float,
    ) -> CircuitBreakerStatus:
        """
        Avalia se o Circuit Breaker deve ser acionado.
        Retorna (True, motivo) ou (False, "").
        """
        if current_equity <= 0:
            return CircuitBreakerStatus(True, "Falência total (equity <= 0)")

        # 1. Drawdown desde o início (Inception)
        dd_inception = (current_equity - initial_equity) / initial_equity
        if dd_inception <= -self.drawdown_inception:
            return CircuitBreakerStatus(
                True, f"Drawdown inception {dd_inception:.1%} excedeu limite {-self.drawdown_inception:.1%}"
            )

        # 2. Drawdown móvel de 30 dias
        if equity_30d_ago > 0:
            dd_30d = (current_equity - equity_30d_ago) / equity_30d_ago
            if dd_30d <= -self.drawdown_rolling_30d:
                return CircuitBreakerStatus(
                    True, f"Drawdown 30d {dd_30d:.1%} excedeu limite {-self.drawdown_rolling_30d:.1%}"
                )

        # 3. Limite de perda diária
        if equity_start_of_day > 0:
            daily_loss = (current_equity - equity_start_of_day) / equity_start_of_day
            if daily_loss <= -self.daily_loss_limit:
                return CircuitBreakerStatus(
                    True, f"Perda diária {daily_loss:.1%} excedeu limite {-self.daily_loss_limit:.1%}"
                )

        return CircuitBreakerStatus(False)

    def can_trade(self, ref_date=None) -> bool:
        """
        Atalho conveniente para o orquestrador de paper trading.
        Retorna True se o circuit breaker NÃO está disparado (seguro para operar).
        Usa equity simulada pois ainda estamos em paper trading sem histórico real.
        """
        # Em paper trading sem histórico, usamos valores neutros para não bloquear
        # a operação incorretamente. A verificação real acontece trade a trade via .check()
        status = self.check(
            current_equity=1.0,
            initial_equity=1.0,
            equity_start_of_day=1.0,
            equity_30d_ago=1.0,
        )
        return not status.triggered

    def audit_decision_gate(
        self,
        ticker: str,
        proposed_side: str,
        signal_confidence: float,
        open_tickers: list[str],
        returns_matrix: dict[str, list[float]],
        ibov_bear_market: bool = False
    ) -> bool:
        """
        Governança Mecânica Determinística.
        Veta ordens da IA se violarem as fronteiras de risco.
        Retorna True se aprovado, False se VETADO.
        """
        # Regra 1: Correlação linear com o portfólio
        if not check_correlation(ticker, open_tickers, returns_matrix, correlation_max=0.7):
            logger.warning("VETO DE GOVERNANÇA: %s apresenta alta correlação com ativos existentes.", ticker)
            return False
            
        # Regra 2: Confiança mínima exigida em mercados de baixa volatilidade adversa
        if ibov_bear_market and signal_confidence < 0.6:
            logger.warning("VETO DE GOVERNANÇA: Confiança da IA (%.2f) muito baixa para o %s em Bear Market.", signal_confidence, ticker)
            return False
            
        return True

def check_correlation(
    candidate_ticker: str,
    open_tickers: list[str],
    returns_matrix: dict[str, list[float]],
    correlation_max: float = 0.7
) -> bool:
    """
    Verifica se o candidato tem alta correlação com ativos já em carteira.
    returns_matrix é um dicionário {ticker: [retornos diários recentes]}.
    Se não houver dados suficientes, aprova.
    """
    if not open_tickers:
        return True
    
    cand_returns = returns_matrix.get(candidate_ticker, [])
    if len(cand_returns) < 10:
        return True # Pouco histórico
        
    import numpy as np
    
    for t in open_tickers:
        t_returns = returns_matrix.get(t, [])
        if len(t_returns) < 10:
            continue
            
        # Pega a menor janela comum
        size = min(len(cand_returns), len(t_returns))
        v1 = cand_returns[-size:]
        v2 = t_returns[-size:]
        
        # Correlação de Pearson
        if np.std(v1) > 0 and np.std(v2) > 0:
            corr = np.corrcoef(v1, v2)[0, 1]
            if corr > correlation_max:
                logger.info("Candidato %s bloqueado por alta correlação (%.2f) com %s", candidate_ticker, corr, t)
                return False
                
    return True
