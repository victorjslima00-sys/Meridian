"""
Liquidez em PRODUÇÃO: ausência de dado BLOQUEIA (fail-closed).

Assimetria deliberada entre backtest e produção — o mesmo dado ausente
significa coisas diferentes nos dois contextos:

  BACKTEST  ausência de ADTV = LACUNA HISTÓRICA. O papel não tinha volume
            registrado naquele dia de 2013. Bloquear a entrada apagaria
            trades por falta de dado, não por iliquidez, e enviesaria a
            medição — foi por isso que `run_regime_backtest` usa fail-SAFE
            (sem ADTV, não bloqueia).

  PRODUÇÃO  ausência de ADTV = FEED DEGRADADO AGORA. O provedor pode estar
            fora do ar, com rate limit, ou devolvendo campo vazio. Entrar
            sem saber a liquidez é exatamente o cenário que o `max_adtv_
            participation` existe para evitar. Aqui vale a regra geral do
            CLAUDE.md: dado não confiável = não age.

A gestão de SAÍDAS não passa por este portão — posição aberta continua sendo
gerida mesmo com o feed de liquidez degradado. Bloquear saída por falta de
dado prenderia capital em risco, que é o oposto de fail-closed.
"""
import pytest

from backend.app.risk.liquidity import (
    LiquidityDecision,
    avaliar_liquidez_para_entrada,
)


class TestLiquidezEmProducaoEhFailClosed:
    def test_ordem_dentro_do_limite_e_aprovada(self):
        """Caminho feliz: ADTV conhecido e ordem pequena o bastante."""
        d = avaliar_liquidez_para_entrada(
            ticker="PETR4.SA", order_value=1_000.0, adtv_brl=10_000_000.0,
            max_participation=0.01,
        )
        assert d.aprovado is True
        assert d.motivo == ""

    def test_ordem_acima_do_limite_e_bloqueada(self):
        """A regra que o backtest também aplica: ordem grande demais para o
        volume do papel não é executável ao preço assumido."""
        d = avaliar_liquidez_para_entrada(
            ticker="XPTO3.SA", order_value=500_000.0, adtv_brl=1_000_000.0,
            max_participation=0.01,
        )
        assert d.aprovado is False
        assert "participacao" in d.motivo

    def test_ADTV_AUSENTE_bloqueia_em_producao(self):
        """A assimetria. No backtest ausência = lacuna histórica e não bloqueia.
        Em produção ausência = feed degradado AGORA, e entrar às cegas é
        exatamente o risco que o limite existe para evitar."""
        for ausente in (None, 0.0, -1.0, float("nan")):
            d = avaliar_liquidez_para_entrada(
                ticker="PETR4.SA", order_value=100.0, adtv_brl=ausente,
                max_participation=0.01,
            )
            assert d.aprovado is False, f"ADTV={ausente!r} deveria bloquear"
            assert "indisponivel" in d.motivo

    def test_limite_desligado_ainda_exige_dado(self):
        """Sutil e importante: `max_participation=0` desliga o TETO, não a
        exigência de dado. Se desligar o teto também desligasse a checagem de
        disponibilidade, um erro de config reabriria a porta em silêncio."""
        d = avaliar_liquidez_para_entrada(
            ticker="PETR4.SA", order_value=100.0, adtv_brl=None,
            max_participation=0.0,
        )
        assert d.aprovado is False
        assert "indisponivel" in d.motivo

    def test_decisao_carrega_os_numeros_para_o_log(self):
        """Bloqueio silencioso é tão ruim quanto entrada às cegas: a decisão
        precisa dizer QUANTO a ordem representava e qual era o teto."""
        d = avaliar_liquidez_para_entrada(
            ticker="XPTO3.SA", order_value=50_000.0, adtv_brl=1_000_000.0,
            max_participation=0.01,
        )
        assert d.participacao == pytest.approx(0.05)
        assert "5.00%" in d.motivo and "1.00%" in d.motivo

    def test_e_dataclass_com_contrato_estavel(self):
        """O portão de entradas consome isto; o contrato não pode mudar por
        acidente."""
        d = avaliar_liquidez_para_entrada(
            ticker="PETR4.SA", order_value=1.0, adtv_brl=1e9, max_participation=0.01,
        )
        assert isinstance(d, LiquidityDecision)
        assert hasattr(d, "aprovado") and hasattr(d, "motivo") and hasattr(d, "participacao")
