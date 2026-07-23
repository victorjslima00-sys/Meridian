"""
Commit 1 da Fase 1 — abstração de Mercado/Corretora.

O sistema nasceu preso à B3 (sufixo .SA no yfinance, fuso e calendário de
Brasília, corretora = simulador de paper trading). O objetivo do usuário é
multi-mercado no futuro (cripto etc.); esta camada existe para que um
mercado novo seja uma IMPLEMENTAÇÃO nova, não uma cirurgia no laço de
trading.

REGRA DESTE COMMIT: refatoração pura, ZERO mudança de comportamento. As
implementações DELEGAM para o código que já existe (feed.py, executor.py,
database.hoje_b3) — nada de lógica nova no caminho de trading. Por isso os
testes abaixo são, em sua maioria, testes de DELEGAÇÃO: provam que passar
pela abstração é indistinguível de chamar a função direto.

`is_open()` é a única capacidade NOVA (horário de pregão vindo do
settings.yaml). Ela é deliberadamente NÃO ligada ao laço de trading neste
commit — ligá-la mudaria comportamento (o bot pararia de operar fora do
pregão, coisa que hoje ele não faz). Fica disponível para quem quiser usar
depois, com decisão explícita.
"""
import datetime
from unittest.mock import patch

import pandas as pd
import pytest

from backend.app.markets import get_broker, get_market, resolve_market
from backend.app.markets.base import Broker, Market


class TestConformidadeDeProtocolo:
    def test_b3_market_satisfaz_o_protocolo_market(self):
        assert isinstance(get_market("b3"), Market)

    def test_paper_broker_satisfaz_o_protocolo_broker(self):
        assert isinstance(get_broker(), Broker)

    def test_mercado_desconhecido_falha_alto_e_claro(self):
        # Fail-closed: pedir um mercado que não existe é erro de programação,
        # não algo para degradar silenciosamente para a B3.
        with pytest.raises(ValueError, match="cripto|desconhecido|unknown"):
            get_market("cripto")


class TestResolveMarketFailClosed:
    """resolve_market descobre o mercado de um ticker TRADEÁVEL pela forma
    do símbolo (estratégia atual, só B3). O ponto crítico: um ticker que
    não casa nenhum mercado conhecido FALHA — nunca cai em B3 por default.
    Este é o tripwire contra o 'conserto rápido' de hardcodar símbolos de
    cripto quando cripto entrar."""

    @pytest.mark.parametrize(
        "ticker",
        ["PETR4.SA", "PETR4", "VALE3", "SANB11", "BBSE3", "sanb11", "  ITUB4.SA  "],
    )
    def test_ticker_b3_resolve_para_b3(self, ticker):
        assert resolve_market(ticker) is get_market("b3")

    @pytest.mark.parametrize(
        "ticker",
        ["BTC-USD", "ETH-USD", "SOL-USD", "AAPL", "SPY", "^BVSP", "GARBAGE", ""],
    )
    def test_ticker_sem_mercado_conhecido_falha_explicitamente(self, ticker):
        # Fail-closed: nunca assume B3. A mensagem aponta para o caminho
        # certo (config explícita), não para hardcodar símbolo.
        with pytest.raises(ValueError, match="NÃO assumir B3|resolução EXPLÍCITA|config"):
            resolve_market(ticker)

    def test_cripto_nao_vira_acao_silenciosamente(self):
        # O bug que só apareceria em produção: BTC-USD tratado como ação B3.
        with pytest.raises(ValueError):
            resolve_market("BTC-USD")


class TestB3MarketNormalizacaoDeSimbolo:
    """A normalização é a regra .SA que hoje vive em feed._normalize_ticker —
    a abstração precisa produzir EXATAMENTE o mesmo resultado."""

    @pytest.mark.parametrize(
        "entrada,esperado",
        [
            ("PETR4", "PETR4.SA"),
            ("PETR4.SA", "PETR4.SA"),
            ("BTC-USD", "BTC-USD"),   # cripto passa direto
            ("^BVSP", "^BVSP"),       # índice passa direto
        ],
    )
    def test_normaliza_igual_ao_feed(self, entrada, esperado):
        assert get_market("b3").normalize_symbol(entrada) == esperado


class TestB3MarketDelegaParaOFeed:
    def test_fetch_ohlcv_delega_para_fetch_recent_data(self):
        df_falso = pd.DataFrame({"close": [1.0, 2.0]})
        with patch(
            "backend.app.data.feed.fetch_recent_data", return_value=df_falso
        ) as mock:
            out = get_market("b3").fetch_ohlcv(
                "PETR4.SA", period="5d", interval="1d", ttl=7.5
            )
        assert out is df_falso
        mock.assert_called_once_with(
            "PETR4.SA", period="5d", interval="1d", ttl=7.5
        )

    def test_current_price_delega_para_get_current_price(self):
        with patch(
            "backend.app.data.feed.get_current_price", return_value=42.5
        ) as mock:
            assert get_market("b3").current_price("VALE3.SA") == 42.5
        mock.assert_called_once_with("VALE3.SA")

    def test_falha_do_feed_propaga_como_none_sem_inventar_dado(self):
        # fail-closed: sem dado confiável, a abstração não fabrica nada.
        with patch("backend.app.data.feed.fetch_recent_data", return_value=None):
            assert get_market("b3").fetch_ohlcv("PETR4.SA") is None


class TestB3MarketCalendario:
    def test_today_usa_o_fuso_da_b3(self):
        from backend.app.data.database import hoje_b3

        assert get_market("b3").today() == hoje_b3()

    @pytest.mark.parametrize(
        "momento,aberto",
        [
            # 2026-07-22 é uma quarta-feira.
            (datetime.datetime(2026, 7, 22, 9, 59), False),   # antes da abertura
            (datetime.datetime(2026, 7, 22, 10, 0), True),    # abertura
            (datetime.datetime(2026, 7, 22, 14, 0), True),    # meio do pregão
            (datetime.datetime(2026, 7, 22, 17, 30), True),   # fechamento (inclusive)
            (datetime.datetime(2026, 7, 22, 17, 31), False),  # depois do fechamento
            (datetime.datetime(2026, 7, 25, 14, 0), False),   # sábado
            (datetime.datetime(2026, 7, 26, 14, 0), False),   # domingo
        ],
    )
    def test_is_open_respeita_horario_e_dia_util(self, momento, aberto):
        tz = get_market("b3").timezone
        assert get_market("b3").is_open(momento.replace(tzinfo=tz)) is aberto


class TestB3MarketUniverso:
    def test_symbols_traz_o_universo_normalizado(self):
        symbols = get_market("b3").symbols()
        assert len(symbols) > 0
        # Todo símbolo já sai pronto para o feed (normalizado).
        m = get_market("b3")
        assert all(s == m.normalize_symbol(s) for s in symbols)


class TestPaperBrokerDelegaParaOExecutor:
    def test_execute_order_delega(self):
        decisao = {"approved": True, "allocated_capital": 10.0}
        analise = {"signal": "BUY", "last_price": 5.0}
        esperado = {"status": "executed"}
        with patch(
            "backend.app.agents.executor.ExecutorAgent.execute_order",
            return_value=esperado,
        ) as mock:
            assert get_broker().execute_order("PETR4.SA", decisao, analise) is esperado
        mock.assert_called_once_with("PETR4.SA", decisao, analise)

    def test_close_order_delega(self):
        esperado = {"status": "closed"}
        with patch(
            "backend.app.agents.executor.ExecutorAgent.close_order",
            return_value=esperado,
        ) as mock:
            assert get_broker().close_order(7, 12.34, "Take Profit") is esperado
        mock.assert_called_once_with(7, 12.34, "Take Profit")
