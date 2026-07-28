"""
Coerência da medição: os otimizadores medem com a MESMA régua do portão.

Três defeitos residuais que sobreviveram às correções anteriores, todos da
mesma família — cada consumidor do backtest reimplementava (ou omitia) uma
parte da modelagem de custo/benchmark:

  1. os otimizadores chamam `run_regime_backtest` SEM `cash_daily_yield`, ou
     seja medem com o caixa ocioso rendendo 0% — exatamente o defeito que
     inverteu o sinal do achado central. Ranquear parâmetros por uma métrica
     que distorce o CAGR é escolher a config errada com aparência de rigor.
  2. `RISK_FREE_RATE_ANNUAL` é a constante mágica 0.10, não a série real do
     BCB — que já está versionada em `cdi_sgs12.csv` desde a correção do
     caixa ocioso. Se a Selic mudar, o portão mede contra 10% em silêncio.

O teste 3 é estrutural: garante que nenhum chamador NOVO esqueça o caixa.
"""
import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

# Módulos que rodam backtest para DECIDIR (ranquear parâmetros, aprovar
# estratégia). Scripts exploratórios ficam de fora de propósito.
CONSUMIDORES_DE_DECISAO = [
    "trading_bot/backtest/optimizer.py",
    "trading_bot/signals/optimizer.py",
    "scripts/fase3_quant_optimizer.py",
]


class TestRiskFreeVemDaSerieReal:
    def test_constante_deriva_do_cdi_medido(self):
        """`RISK_FREE_RATE_ANNUAL` tem de vir da série do BCB, não de um
        número escrito à mão. A regra do CLAUDE.md é explícita: nunca usar
        número inventado quando já existe o equivalente no sistema."""
        from trading_bot.backtest.metrics import RISK_FREE_RATE_ANNUAL
        from trading_bot.data.risk_free import cdi_annualized

        assert RISK_FREE_RATE_ANNUAL == pytest.approx(cdi_annualized(), abs=1e-9)

    def test_valor_e_plausivel_para_o_brasil(self):
        """Guarda contra a série sumir e a função devolver 0 — que reintroduz
        silenciosamente o bug de 'Sharpe contra risk-free zero'."""
        from trading_bot.backtest.metrics import RISK_FREE_RATE_ANNUAL

        assert 0.02 < RISK_FREE_RATE_ANNUAL < 0.25

    def test_nao_e_mais_a_constante_magica(self):
        """O 0.10 acertava por coincidência (CDI medido: 10,08%). Coincidência
        não é fonte de verdade."""
        from trading_bot.backtest.metrics import RISK_FREE_RATE_ANNUAL

        assert RISK_FREE_RATE_ANNUAL != 0.10


class TestOtimizadoresCreditamOCaixa:
    @pytest.mark.parametrize("caminho", CONSUMIDORES_DE_DECISAO)
    def test_passa_cash_daily_yield_ao_backtest(self, caminho):
        """Estrutural, não comportamental: um teste de comportamento exigiria
        rodar o otimizador inteiro (minutos). A varredura de AST pega a
        omissão — e pega também o chamador NOVO que alguém adicionar amanhã."""
        arquivo = RAIZ / caminho
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
        chamadas = [
            no for no in ast.walk(arvore)
            if isinstance(no, ast.Call)
            and getattr(no.func, "id", getattr(no.func, "attr", None)) == "run_regime_backtest"
        ]
        assert chamadas, f"{caminho} não chama run_regime_backtest — teste desatualizado?"
        for c in chamadas:
            kwargs = {k.arg for k in c.keywords}
            assert "cash_daily_yield" in kwargs, (
                f"{caminho}:{c.lineno} chama run_regime_backtest sem cash_daily_yield — "
                "mede com caixa ocioso a 0%, que foi o defeito que inverteu o "
                "sinal do achado central."
            )


class TestSaneamentoNaoVaiParaOFeedAoVivo:
    """DECISÃO REGISTRADA: o filtro de sanidade fica FORA do feed ao vivo.

    Os dois critérios são calibrados para barra DIÁRIA e não transferem para
    as janelas que o feed usa (`period="1d", interval="1m"`):

      - o limiar de R$100k é volume de um DIA. Perguntado a uma barra de 1
        minuto, vira "este minuto negociou R$100k?" — que para papel de
        liquidez média é NÃO legitimamente. Medido: GFSA3 100% das barras
        abaixo do limiar, AGRO3 100%, TCSA3 100%, CVCB3 88%.
      - o corte de 4 fechamentos iguais é anormal em barra diária e NORMAL em
        barra de minuto (papel parado em minuto fraco). Medido: GFSA3 78%
        das barras de 1min em "congelamento".

    Ligar o filtro ali apagaria o feed inteiro dos papéis menos líquidos —
    e, pior, faria isso em SILÊNCIO, no caminho que gerencia saída de posição
    com dinheiro em risco.

    A proteção correta no caminho ao vivo é outra e já existe:
    `backend.app.risk.liquidity` (fail-closed na entrada) e o
    `_price_is_trustworthy` do feed (frescor da cotação). Dado histórico
    corrompido e feed degradado agora são problemas distintos.
    """

    def test_feed_ao_vivo_nao_importa_o_saneador(self):
        import ast

        feed = RAIZ / "backend/app/data/feed.py"
        arvore = ast.parse(feed.read_text(encoding="utf-8"), filename=str(feed))
        nomes = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.ImportFrom) and no.module:
                nomes.add(no.module)
            elif isinstance(no, ast.Import):
                nomes.update(a.name for a in no.names)
        assert "trading_bot.data.sanity" not in nomes, (
            "O saneador é calibrado para barra DIÁRIA; no feed ao vivo (1min) "
            "descartaria até 100% das barras de papéis de liquidez média. "
            "Ver docstring desta classe."
        )
