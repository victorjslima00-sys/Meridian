"""
`calculate_sharpe_ratio` ranqueava parâmetros contra risk-free ZERO.

Não é o portão de aprovação — `metrics.py::_trade_sharpe` já subtrai
risk-free e reprovou a estratégia atual. Este é o que **ESCOLHE** parâmetros
numa varredura (`optimizer.py:65` ordena os resultados por este Sharpe).
Ranquear contra zero seleciona configurações que batem ZERO, não o CDI, e
entrega o resultado com aparência de rigor: varredura ampla, ranking,
melhor configuração no topo. Num país com juros de dois dígitos, "melhor que
zero" é um filtro que não filtra nada.

Segundo defeito, mais silencioso: a taxa era subtraída de `mean_return`, que
é um retorno DIÁRIO — então o parâmetro tinha de ser diário, enquanto o nome
e a docstring ("Anualizado") convidavam a passar taxa anual. Quem passasse
0.10 achando "10% a.a." subtrairia 10% POR DIA.
"""
import pytest

from trading_bot.backtest.metrics import RISK_FREE_RATE_ANNUAL, TRADING_DAYS_PER_YEAR
from trading_bot.backtest.optimizer import calculate_sharpe_ratio


def _curva(retorno_anual: float, vol_diaria: float = 0.005, dias: int = 504) -> list[float]:
    """Curva de patrimônio com retorno anual composto EXATO e volatilidade
    determinística (alterna +v/-v em torno do drift, contagem par → a média
    dos retornos diários é exatamente o drift)."""
    g = (1 + retorno_anual) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    eq = [1000.0]
    for i in range(dias):
        eq.append(eq[-1] * (1 + g + (vol_diaria if i % 2 == 0 else -vol_diaria)))
    return eq


class TestSharpeDoOtimizadorUsaRiskFreeReal:
    def test_estrategia_abaixo_do_risk_free_tem_sharpe_negativo(self):
        """O defeito, no caso que importa: 5% a.a. num mundo de 10% a.a. é
        PIOR que não fazer nada. Contra zero aparecia como positivo — e uma
        varredura o colocaria no topo do ranking."""
        assert calculate_sharpe_ratio(_curva(0.05)) < 0

    def test_estrategia_acima_do_risk_free_tem_sharpe_positivo(self):
        """Contraprova: o sinal não é sempre negativo — quem bate o
        risk-free continua pontuando positivo."""
        assert calculate_sharpe_ratio(_curva(0.20)) > 0

    def test_no_risk_free_exato_o_sharpe_e_zero(self):
        """A fronteira: render exatamente o risk-free é excesso zero."""
        assert calculate_sharpe_ratio(_curva(RISK_FREE_RATE_ANNUAL)) == pytest.approx(0.0, abs=1e-9)

    def test_taxa_e_interpretada_como_ANUAL_e_nao_diaria(self):
        """A armadilha de unidade. Passar 0.10 significa 10% AO ANO. Se o
        valor fosse tratado como taxa diária, uma curva que rende exatamente
        10% a.a. teria Sharpe absurdamente negativo em vez de zero."""
        sharpe = calculate_sharpe_ratio(_curva(0.10), risk_free_annual=0.10)
        assert sharpe == pytest.approx(0.0, abs=1e-9)

    def test_default_vem_da_mesma_fonte_do_portao(self):
        """Uma fonte de verdade: o otimizador e o portão têm de usar o MESMO
        risk-free, senão a varredura escolhe por uma régua e a aprovação
        mede por outra."""
        curva = _curva(0.07)
        assert calculate_sharpe_ratio(curva) == pytest.approx(
            calculate_sharpe_ratio(curva, risk_free_annual=RISK_FREE_RATE_ANNUAL)
        )

    def test_ranking_nao_promove_quem_perde_do_risk_free(self):
        """O efeito prático numa varredura: ordenar por Sharpe não pode
        deixar uma configuração que perde do risk-free acima de zero."""
        candidatos = {"perde": _curva(0.04), "empata": _curva(RISK_FREE_RATE_ANNUAL), "ganha": _curva(0.25)}
        ranking = sorted(
            ((n, calculate_sharpe_ratio(c)) for n, c in candidatos.items()),
            key=lambda x: x[1], reverse=True,
        )
        assert [n for n, _ in ranking] == ["ganha", "empata", "perde"]
        assert dict(ranking)["perde"] < 0, "configuração que perde do risk-free pontuou positivo"
