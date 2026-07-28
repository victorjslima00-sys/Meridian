"""
Filtro de sanidade: descartar o PREGÃO implausível, não o ano inteiro.

A auditoria de dados (2026-07-27) mostrou que o yfinance serve, para tickers
brasileiros, dois defeitos objetivos e silenciosos:

  - volume financeiro implausível (11,6% dos pregões < R$100k/dia; PCAR3, blue
    chip há décadas, aparece com 3 ações/dia em 2008);
  - fechamento CONGELADO por dezenas ou centenas de pregões (4,78% do total;
    UGPA3 fica 590 pregões fixo em R$3.302.501,25).

O dilema aparente era escolher entre 15 anos de dado sujo e 7 anos limpos. Este
módulo é a terceira via: **remover a barra ruim e manter a janela**. Uma barra
descartada vira ausência de dado — o indicador simplesmente não a vê —, que é
mais honesto que propagar um número inventado.

Deliberadamente NÃO filtra por retorno extremo: queda de 50% num dia existe de
verdade (limite, crise, fraude revelada), e descartá-la apagaria justamente os
eventos que a estratégia precisa enfrentar. Os dois critérios acima são
objetivos; "retorno grande demais" não é.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from trading_bot.data.sanity import sanitize_ohlcv


def _serie(n=40, preco=10.0, vol=1_000_000.0):
    return pd.DataFrame({
        "ts": pd.date_range("2020-01-01", periods=n, freq="D").date,
        "o": [preco] * n, "h": [preco * 1.01] * n, "l": [preco * 0.99] * n,
        "c": [preco + i * 0.01 for i in range(n)],
        "adj_close": [preco + i * 0.01 for i in range(n)],
        "v": [vol / preco] * n,
    })


class TestFiltroDeSanidade:
    def test_serie_boa_passa_intacta(self):
        """Guarda de regressão: dado plausível não pode ser tocado."""
        df = _serie()
        out = sanitize_ohlcv(df)
        assert len(out) == len(df)
        assert out["c"].tolist() == df["c"].tolist()

    def test_descarta_pregao_com_volume_financeiro_implausivel(self):
        """O caso PCAR3: volume financeiro de centenas de reais/dia num papel
        que negocia milhões. Não é iliquidez — é dado ausente."""
        df = _serie()
        df.loc[5:9, "v"] = 1.0          # 5 pregões com ~R$10/dia
        out = sanitize_ohlcv(df, min_financial_volume=100_000.0)
        assert len(out) == len(df) - 5
        assert (out["c"] * out["v"] >= 100_000.0).all()

    def test_descarta_bloco_de_fechamento_congelado(self):
        """O caso UGPA3/SUZB3: centenas de pregões com o MESMO fechamento.
        Nenhum papel real faz isso — é backfill de série remontada."""
        df = _serie()
        df.loc[10:19, "c"] = 7.77
        df.loc[10:19, "adj_close"] = 7.77
        out = sanitize_ohlcv(df, max_frozen_run=4)
        assert len(out) < len(df)
        # nenhum bloco congelado longo sobrevive
        c = out["c"].values
        run = maior = 0
        for i in range(1, len(c)):
            run = run + 1 if c[i] == c[i - 1] else 0
            maior = max(maior, run)
        assert maior < 4

    def test_congelamento_curto_e_preservado(self):
        """Dois ou três fechamentos iguais acontecem de verdade (papel parado
        em pregão fraco). O filtro não pode confundir isso com dado morto."""
        df = _serie()
        df.loc[10:11, "c"] = 7.77
        df.loc[10:11, "adj_close"] = 7.77
        out = sanitize_ohlcv(df, max_frozen_run=4)
        assert len(out) == len(df)

    def test_nao_filtra_retorno_extremo(self):
        """Decisão explícita: -60% num dia é evento REAL (fraude revelada,
        limite). Apagá-lo removeria exatamente o que a estratégia precisa
        aguentar — e enviesaria o backtest para cima."""
        df = _serie()
        df.loc[20, "c"] = df.loc[19, "c"] * 0.4
        df.loc[20, "adj_close"] = df.loc[20, "c"]
        out = sanitize_ohlcv(df)
        assert len(out) == len(df)

    def test_idempotente(self):
        """Aplicar duas vezes tem de dar o mesmo resultado — senão o filtro
        estaria comendo dado bom a cada passada."""
        df = _serie()
        df.loc[5:9, "v"] = 1.0
        df.loc[15:25, "c"] = 8.88
        df.loc[15:25, "adj_close"] = 8.88
        uma = sanitize_ohlcv(df)
        duas = sanitize_ohlcv(uma)
        assert len(uma) == len(duas)
        assert uma["ts"].tolist() == duas["ts"].tolist()

    def test_serie_vazia_ou_curta_nao_quebra(self):
        """Fail-safe: entrada degenerada retorna vazio/curto sem exceção."""
        assert len(sanitize_ohlcv(pd.DataFrame(columns=["ts", "c", "v", "adj_close"]))) == 0
        assert len(sanitize_ohlcv(_serie(n=2))) == 2

    def test_relatorio_de_descarte(self):
        """O filtro tem de dizer QUANTO descartou e por quê — descarte
        silencioso é o mesmo pecado do dado silenciosamente errado."""
        df = _serie()
        df.loc[5:9, "v"] = 1.0
        out, rel = sanitize_ohlcv(df, return_report=True)
        assert rel["descartados_volume"] == 5
        assert rel["descartados_congelamento"] == 0
        assert rel["total_entrada"] == len(df)
        assert rel["total_saida"] == len(out)


class TestFiltroLigadoAoIngestor:
    """O saneamento na PORTA DE ENTRADA: o dado sujo nunca chega ao backtest,
    ao otimizador ou ao relatório. Sanear em cada consumidor seria repetir a
    regra em N lugares e esquecer num deles."""

    def _df_sujo(self):
        import numpy as np
        n = 30
        return pd.DataFrame({
            "ticker": ["X"] * n,
            "ts": pd.date_range("2020-01-01", periods=n, freq="D").date,
            "o": [10.0] * n, "h": [10.1] * n, "l": [9.9] * n,
            "c": [10.0 + i * 0.01 for i in range(n)],
            "adj_close": [10.0 + i * 0.01 for i in range(n)],
            "v": [100_000.0] * n,
        })

    def test_fetch_yfinance_saneia_por_padrao(self, monkeypatch):
        from trading_bot.data import ingestion

        sujo = self._df_sujo()
        sujo.loc[5:9, "v"] = 0.01           # volume financeiro ~R$0,10
        monkeypatch.setattr(ingestion, "_normalize", lambda df, t: sujo)
        monkeypatch.setattr(
            ingestion.yf, "download",
            lambda *a, **k: pd.DataFrame({"Close": [1.0]}),
        )
        out = ingestion.fetch_yfinance("X", date(2020, 1, 1))
        assert len(out) == len(sujo) - 5

    def test_pode_ser_desligado_explicitamente(self, monkeypatch):
        """Escape hatch para quem precisar do dado cru (auditoria de fonte,
        comparação antes/depois). Desligar tem de ser DELIBERADO."""
        from trading_bot.data import ingestion

        sujo = self._df_sujo()
        sujo.loc[5:9, "v"] = 0.01
        monkeypatch.setattr(ingestion, "_normalize", lambda df, t: sujo)
        monkeypatch.setattr(
            ingestion.yf, "download",
            lambda *a, **k: pd.DataFrame({"Close": [1.0]}),
        )
        out = ingestion.fetch_yfinance("X", date(2020, 1, 1), sanitize=False)
        assert len(out) == len(sujo)


class TestSaneadorNuncaDerrubaOPipeline:
    """Um filtro de sanidade que estoura é pior que dado sujo: derruba a
    ingestão inteira. Schema incompleto tem de degradar para o critério que
    ainda dá para aplicar."""

    def test_sem_coluna_de_volume_aplica_so_o_congelamento(self):
        df = _serie(n=30).drop(columns=["v"])
        df.loc[10:20, "c"] = 7.77
        df.loc[10:20, "adj_close"] = 7.77
        out = sanitize_ohlcv(df)
        assert len(out) < len(df)          # congelamento ainda pega
        assert "v" not in out.columns      # e não inventa a coluna

    def test_sem_coluna_de_fechamento_devolve_intacto(self):
        df = _serie(n=10).drop(columns=["c"])
        out = sanitize_ohlcv(df)
        assert len(out) == len(df)
