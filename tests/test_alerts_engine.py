"""
Testes unitarios para o Motor de Gerenciamento de Alertas e Notificacoes (Vulcan DevOps)
"""
import pytest
from trading_bot.infra.alerts_engine import AlertMessage, AlertsEngine


def test_alert_message_creation():
    msg = AlertMessage(
        level="CRITICAL",
        sector="RISK",
        title="Circuit Breaker Acionado",
        details="Drawdown ultrapassou limite maximo permitido de 10%.",
    )
    assert msg.level == "CRITICAL"
    assert msg.sector == "RISK"
    assert "timestamp_utc" in msg.to_dict()


def test_alerts_engine_dispatch():
    engine = AlertsEngine()
    msg = AlertMessage(
        level="WARNING",
        sector="INFRA",
        title="Disco Proximo do Limite",
        details="Espaco livre inferior a 5 GB.",
    )
    res = engine.dispatch(msg)
    
    assert res["dispatched"] is True
    assert len(engine.history) == 1
    assert engine.history[0]["level"] == "WARNING"
