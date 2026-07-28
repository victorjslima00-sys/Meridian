"""
Filtro de liquidez ligado ao portão de ENTRADA em produção.

A pesquisa mediu que limitar a ordem a 1% do ADTV move o teto de capacidade de
~R$10-50k para R$100k (BACKLOG, seção da varredura). Ao vivo o filtro tem outro
papel além do teto: recusar entrada quando NÃO SE SABE a liquidez.

Assimetria já registrada em `backend/app/risk/liquidity.py`:
  BACKTEST  ADTV ausente = lacuna histórica  -> não bloqueia (fail-SAFE)
  PRODUÇÃO  ADTV ausente = feed degradado    -> bloqueia    (fail-CLOSED)

Escopo: só ENTRADAS. A gestão de saídas roda por outro laço (`exit_loop`) e
não passa por aqui — bloquear saída por falta de dado prenderia capital em
risco, que é o oposto de fail-closed.
"""
import pytest

from backend.app.risk.liquidity import avaliar_liquidez_para_entrada


class TestPortaoDeLiquidezNoRuntime:
    def test_adtv_do_dataframe_do_feed(self):
        """`adtv_do_feed` calcula volume financeiro médio a partir do DataFrame
        que o feed ao vivo já devolve — sem chamada extra de rede, sem fonte
        nova. Se exigisse outro provedor, viraria arquitetura nova."""
        import pandas as pd

        from backend.app.risk.liquidity import adtv_do_feed

        df = pd.DataFrame({
            "close": [10.0] * 30,
            "volume": [50_000.0] * 30,   # 30 pregões a R$500k/dia
        })
        assert adtv_do_feed(df) == pytest.approx(500_000.0)

    def test_adtv_ausente_ou_schema_incompleto_devolve_none(self):
        """None é o sinal de 'não sei' — e em produção 'não sei' bloqueia.
        Devolver 0.0 aqui seria pior: 0 é um número, e números passam por
        comparações silenciosamente."""
        import pandas as pd

        from backend.app.risk.liquidity import adtv_do_feed

        assert adtv_do_feed(None) is None
        assert adtv_do_feed(pd.DataFrame()) is None
        assert adtv_do_feed(pd.DataFrame({"close": [1.0]})) is None  # sem volume

    def test_ordem_dentro_do_teto_passa(self):
        d = avaliar_liquidez_para_entrada(
            ticker="PETR4.SA", order_value=1_000.0,
            adtv_brl=10_000_000.0, max_participation=0.01,
        )
        assert d.aprovado is True

    def test_ordem_acima_do_teto_bloqueia_com_os_numeros_no_motivo(self):
        """Bloqueio silencioso é tão ruim quanto entrada às cegas: o log
        precisa dizer quanto a ordem representava e qual era o teto."""
        d = avaliar_liquidez_para_entrada(
            ticker="XPTO3.SA", order_value=50_000.0,
            adtv_brl=1_000_000.0, max_participation=0.01,
        )
        assert d.aprovado is False
        assert "5.00%" in d.motivo and "1.00%" in d.motivo

    def test_sem_liquidez_bloqueia_em_producao(self):
        """A assimetria: no backtest ausência não bloqueia; aqui bloqueia."""
        d = avaliar_liquidez_para_entrada(
            ticker="PETR4.SA", order_value=100.0,
            adtv_brl=None, max_participation=0.01,
        )
        assert d.aprovado is False
        assert "indisponivel" in d.motivo


class TestConfiguracaoDoTeto:
    def test_teto_vem_do_settings_e_nao_e_numero_magico(self):
        """CLAUDE.md: nunca usar número inventado quando existe o equivalente
        configurado. O X=1% saiu de medição — tem de estar no settings.yaml,
        não hardcoded no meio do laço de entradas."""
        from backend.app.risk.liquidity import max_participation_configurada

        x = max_participation_configurada()
        assert 0.0 < x <= 0.05, f"teto implausível: {x}"

    def test_valor_configurado_e_o_que_a_pesquisa_validou(self):
        from backend.app.risk.liquidity import max_participation_configurada

        assert max_participation_configurada() == pytest.approx(0.01)
