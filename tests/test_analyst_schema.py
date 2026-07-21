"""
Track A (fix/llm-pydantic-validation): AnalystDecision -- schema Pydantic
pra resposta do LLM, substituindo a checagem aritmética solta que existia
em risk_manager.py (risk<=0 or reward<=0). CLAUDE.md: "Toda resposta de
LLM ... validada com Pydantic e invariantes semânticas (em BUY: stop_loss
< preço < target_price)".

Limites de distância NÃO são números inventados: max_stop = signals.stop_pct
(0.04, já documentado em settings.yaml como "Stop-loss rígido de emergência
-- Hard Cap") e max_target = stop_pct * (target_atr_mult/stop_atr_mult) =
0.04 * (3.0/1.5) = 0.08, mesma razão risco:retorno já usada pelo motor de
sinais técnico (donchian breakout) do projeto.
"""
import pytest
from pydantic import ValidationError

from backend.app.agents.schemas import AnalystDecision


class TestAnalystDecisionCasosValidos:
    def test_buy_valido_dentro_dos_limites(self):
        d = AnalystDecision(
            signal="BUY", confidence=70, target_price=136.0,
            stop_loss=126.0, reason="Uptrend confirmado", current_price=130.0,
        )
        assert d.signal == "BUY"

    def test_sell_valido_dentro_dos_limites(self):
        d = AnalystDecision(
            signal="SELL", confidence=70, target_price=95.0,
            stop_loss=103.0, reason="Downtrend confirmado", current_price=100.0,
        )
        assert d.signal == "SELL"

    def test_hold_nao_exige_precos(self):
        d = AnalystDecision(
            signal="HOLD", confidence=0, target_price=0.0,
            stop_loss=0.0, reason="Sem direção clara", current_price=100.0,
        )
        assert d.signal == "HOLD"


class TestAnalystDecisionRejeitaSinalInvalido:
    def test_sinal_fora_do_enum_e_rejeitado(self):
        with pytest.raises(ValidationError):
            AnalystDecision(
                signal="LONG", confidence=70, target_price=136.0,
                stop_loss=126.0, reason="x", current_price=130.0,
            )

    def test_confidence_fora_da_faixa_e_rejeitado(self):
        with pytest.raises(ValidationError):
            AnalystDecision(
                signal="BUY", confidence=150, target_price=136.0,
                stop_loss=126.0, reason="x", current_price=130.0,
            )


class TestAnalystDecisionInvarianteDeOrdemDePreco:
    def test_buy_com_stop_acima_do_preco_atual_e_rejeitado(self):
        with pytest.raises(ValidationError, match="stop_loss < preço_atual < target_price"):
            AnalystDecision(
                signal="BUY", confidence=70, target_price=136.0,
                stop_loss=131.0,  # stop ACIMA do preço atual -- inválido pra BUY
                reason="x", current_price=130.0,
            )

    def test_buy_com_target_abaixo_do_preco_atual_e_rejeitado(self):
        with pytest.raises(ValidationError, match="stop_loss < preço_atual < target_price"):
            AnalystDecision(
                signal="BUY", confidence=70, target_price=129.0,  # target ABAIXO do preço atual
                stop_loss=126.0, reason="x", current_price=130.0,
            )

    def test_sell_com_target_acima_do_preco_atual_e_rejeitado(self):
        with pytest.raises(ValidationError, match="target_price < preço_atual < stop_loss"):
            AnalystDecision(
                signal="SELL", confidence=70, target_price=101.0,  # target ACIMA do preço atual
                stop_loss=103.0, reason="x", current_price=100.0,
            )

    def test_sell_com_stop_abaixo_do_preco_atual_e_rejeitado(self):
        with pytest.raises(ValidationError, match="target_price < preço_atual < stop_loss"):
            AnalystDecision(
                signal="SELL", confidence=70, target_price=95.0,
                stop_loss=99.0,  # stop ABAIXO do preço atual -- inválido pra SELL
                reason="x", current_price=100.0,
            )

    def test_precos_zerados_em_buy_sao_rejeitados(self):
        with pytest.raises(ValidationError, match="positivos"):
            AnalystDecision(
                signal="BUY", confidence=70, target_price=0.0,
                stop_loss=0.0, reason="x", current_price=130.0,
            )


class TestAnalystDecisionLimiteDeDistancia:
    def test_stop_alem_do_limite_de_4pct_e_rejeitado(self):
        # 130 -> stop a 5% (123.5) excede o limite de signals.stop_pct (4%)
        with pytest.raises(ValidationError, match="Stop"):
            AnalystDecision(
                signal="BUY", confidence=70, target_price=136.0,
                stop_loss=123.5, reason="x", current_price=130.0,
            )

    def test_target_alem_do_limite_de_8pct_e_rejeitado(self):
        # 130 -> alvo a 10% (143.0) excede o limite derivado (8%)
        with pytest.raises(ValidationError, match="Alvo"):
            AnalystDecision(
                signal="BUY", confidence=70, target_price=143.0,
                stop_loss=126.0, reason="x", current_price=130.0,
            )

    def test_stop_claramente_dentro_do_limite_e_aceito(self):
        # 130 -> stop a 3.85% (125.0), abaixo do limite de 4% com folga
        # suficiente pra não esbarrar em imprecisão de ponto flutuante.
        d = AnalystDecision(
            signal="BUY", confidence=70, target_price=136.0,
            stop_loss=125.0, reason="x", current_price=130.0,
        )
        assert d.stop_loss == 125.0
