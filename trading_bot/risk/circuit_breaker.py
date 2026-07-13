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
        # FAIL-FAST: threshold com sinal errado inverte a lógica do check()
        # (dispararia sempre) — melhor recusar a config do que operar com ela.
        for nome, valor in (
            ("daily_loss_limit", daily_loss_limit),
            ("drawdown_inception", drawdown_inception),
            ("drawdown_rolling_30d", drawdown_rolling_30d),
        ):
            if not isinstance(valor, (int, float)) or not 0 < valor <= 0.5:
                raise ValueError(
                    f"Circuit breaker: {nome}={valor!r} inválido — "
                    "esperado número em (0, 0.5]. Corrija risk.circuit_breaker "
                    "no settings.yaml (valores POSITIVOS)."
                )
        self.daily_loss_limit = daily_loss_limit
        self.drawdown_inception = drawdown_inception
        self.drawdown_rolling_30d = drawdown_rolling_30d

    @classmethod
    def from_config(cls) -> "CircuitBreaker":
        """
        Instancia com os limites de config/settings.yaml (risk.circuit_breaker).
        Chaves ausentes usam os defaults do construtor; valores inválidos ou
        falha ao carregar a config levantam exceção (fail-fast) — os chamadores
        tratam exceção como bloqueio de novas entradas (fail-closed).
        """
        from trading_bot.core.config import AppConfig
        cb_cfg = AppConfig.load().get("risk", "circuit_breaker", default={}) or {}
        kwargs = {
            nome: cb_cfg[nome]
            for nome in ("daily_loss_limit", "drawdown_inception", "drawdown_rolling_30d")
            if nome in cb_cfg
        }
        return cls(**kwargs)

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
        Retorna True se o circuit breaker NÃO está disparado (seguro para operar).

        FAIL-CLOSED: sem snapshots de equity suficientes ou com erro de banco,
        retorna False (bloqueia novas entradas; gestão de saídas não passa por aqui).
        """
        try:
            from backend.app.data.database import compute_current_equity, get_equity_refs

            refs = get_equity_refs(ref_date)
            if refs is None:
                logger.warning(
                    "CIRCUIT BREAKER FAIL-CLOSED: nenhum equity_snapshot disponível — "
                    "bloqueando novas entradas até o primeiro snapshot do dia."
                )
                return False

            current_equity = compute_current_equity()
        except Exception as e:
            logger.error(
                f"CIRCUIT BREAKER FAIL-CLOSED: erro ao obter equity/snapshots ({e}) — "
                "bloqueando novas entradas."
            )
            return False

        status = self.check(
            current_equity=current_equity,
            initial_equity=refs["initial"],
            equity_start_of_day=refs["start_of_day"],
            equity_30d_ago=refs["equity_30d"],
        )
        if status.triggered:
            logger.warning(f"CIRCUIT BREAKER ACIONADO: {status.reason}")
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
