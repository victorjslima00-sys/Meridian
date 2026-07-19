"""
P3-A Etapa 2d — cache de preço em feed.py.
=============================================
Sem cache, N posições ativas em exit_loop geram N requisições de rede a
cada EXIT_INTERVAL_SECONDS (~5s) — com poucas posições simultâneas já se
bate no rate limit que este projeto mediu empiricamente (ver BACKLOG.md).
O cache desacopla a taxa de rede do número de chamadores/laços.

fetch_recent_data roda em threads reais via asyncio.to_thread (não em
corrotinas) — por isso os testes de concorrência aqui usam threading.Lock/
threading.Barrier, não asyncio, mesmo raciocínio da Etapa 1.
"""
import threading
import time
from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

from backend.app import worker_state
from backend.app.data import feed


def _make_yf_df(close=35.0, n=3):
    """DataFrame no formato bruto retornado por yf.download (colunas
    capitalizadas, índice de data) — antes da normalização que
    fetch_recent_data aplica."""
    idx = pd.date_range("2026-07-18", periods=n, freq="15min")
    return pd.DataFrame(
        {
            "Open": [close] * n, "High": [close] * n,
            "Low": [close] * n, "Close": [close] * n,
            "Volume": [1000] * n,
        },
        index=idx,
    )


class TestPriceCacheBasics:
    def test_segunda_chamada_dentro_do_ttl_nao_bate_na_rede(self):
        with patch(
            "backend.app.data.feed.yf.download", side_effect=lambda *a, **kw: _make_yf_df()
        ) as mock_dl:
            r1 = feed.fetch_recent_data("PETR4.SA", period="1d", interval="15m")
            r2 = feed.fetch_recent_data("PETR4.SA", period="1d", interval="15m")

        assert mock_dl.call_count == 1
        assert r1 is not None and r2 is not None
        assert r1.equals(r2)

    def test_ticker_diferente_nao_reusa_cache(self):
        with patch(
            "backend.app.data.feed.yf.download", side_effect=lambda *a, **kw: _make_yf_df()
        ) as mock_dl:
            feed.fetch_recent_data("PETR4.SA", period="1d", interval="15m")
            feed.fetch_recent_data("VALE3.SA", period="1d", interval="15m")

        assert mock_dl.call_count == 2

    def test_period_ou_interval_diferente_nao_reusa_cache(self):
        with patch(
            "backend.app.data.feed.yf.download", side_effect=lambda *a, **kw: _make_yf_df()
        ) as mock_dl:
            feed.fetch_recent_data("PETR4.SA", period="1d", interval="15m")
            feed.fetch_recent_data("PETR4.SA", period="5d", interval="15m")

        assert mock_dl.call_count == 2

    def test_cache_expira_apos_ttl(self):
        with patch.object(feed, "PRICE_CACHE_TTL_SECONDS", 0.05), \
             patch(
                 "backend.app.data.feed.yf.download", side_effect=lambda *a, **kw: _make_yf_df()
             ) as mock_dl:
            feed.fetch_recent_data("ITUB4.SA", period="1d", interval="15m")
            time.sleep(0.12)
            feed.fetch_recent_data("ITUB4.SA", period="1d", interval="15m")

        assert mock_dl.call_count == 2

    def test_copia_retornada_nao_e_a_mesma_referencia_do_cache(self):
        """Mutar o DataFrame retornado não pode corromper o cache."""
        with patch(
            "backend.app.data.feed.yf.download", side_effect=lambda *a, **kw: _make_yf_df()
        ):
            r1 = feed.fetch_recent_data("BBDC4.SA", period="1d", interval="15m")
            r1.iloc[0, r1.columns.get_loc("close")] = -999.0  # mutação
            r2 = feed.fetch_recent_data("BBDC4.SA", period="1d", interval="15m")

        assert r2.iloc[0]["close"] != -999.0


class TestPriceCacheNeverCachesFailure:
    def test_falha_nao_e_cacheada_proxima_chamada_tenta_de_novo(self):
        with patch(
            "backend.app.data.feed.yf.download",
            side_effect=ConnectionError("feed fora do ar"),
        ) as mock_dl, patch("backend.app.data.feed.time.sleep"):
            r1 = feed.fetch_recent_data(
                "MGLU3.SA", period="1d", interval="15m", max_retries=2
            )
        assert r1 is None
        primeira_tentativa_count = mock_dl.call_count
        assert primeira_tentativa_count == 2  # esgotou max_retries, nada cacheado

        with patch(
            "backend.app.data.feed.yf.download", side_effect=lambda *a, **kw: _make_yf_df()
        ) as mock_dl2:
            r2 = feed.fetch_recent_data(
                "MGLU3.SA", period="1d", interval="15m", max_retries=2
            )
        # Bateu na rede de novo — não achou (nem deveria) uma "falha cacheada"
        assert mock_dl2.call_count == 1
        assert r2 is not None

    def test_dados_vazios_tambem_nao_sao_cacheados(self):
        empty_df = pd.DataFrame()
        with patch(
            "backend.app.data.feed.yf.download", return_value=empty_df
        ) as mock_dl, patch("backend.app.data.feed.time.sleep"):
            r1 = feed.fetch_recent_data(
                "AGRO3.SA", period="1d", interval="15m", max_retries=2
            )
        assert r1 is None

        with patch(
            "backend.app.data.feed.yf.download", side_effect=lambda *a, **kw: _make_yf_df()
        ) as mock_dl2:
            r2 = feed.fetch_recent_data(
                "AGRO3.SA", period="1d", interval="15m", max_retries=2
            )
        assert mock_dl2.call_count == 1
        assert r2 is not None


class TestPriceCacheConcurrency:
    def test_duas_threads_pedindo_a_mesma_chave_ao_mesmo_tempo_geram_1_requisicao(
        self,
    ):
        """O bug que a Etapa 1 já resolveu em outra roupa: duas 'origens'
        concorrentes pedindo o mesmo dado não podem cada uma disparar sua
        própria requisição de rede. threading.Barrier força overlap real;
        o mock de yf.download é deliberadamente lento (0.3s) para garantir
        que a segunda thread chegue no cache/lock ENQUANTO a primeira ainda
        está buscando — sem essa janela larga, a race não teria chance
        real de se manifestar no teste."""
        call_count = {"n": 0}
        count_lock = threading.Lock()

        def slow_download(*args, **kwargs):
            with count_lock:
                call_count["n"] += 1
            time.sleep(0.3)
            return _make_yf_df()

        barrier = threading.Barrier(2)
        results = [None, None]

        def worker(idx):
            barrier.wait()
            results[idx] = feed.fetch_recent_data(
                "WEGE3.SA", period="1d", interval="15m"
            )

        with patch(
            "backend.app.data.feed.yf.download", side_effect=slow_download
        ):
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        assert call_count["n"] == 1, (
            f"Esperada 1 requisição de rede para a mesma chave concorrente, "
            f"obtidas {call_count['n']}"
        )
        assert results[0] is not None and results[1] is not None
        assert results[0].equals(results[1])

    def test_tickers_diferentes_concorrentes_nao_se_bloqueiam_por_um_lock_global(
        self,
    ):
        """Locks por CHAVE, não um lock único: tickers diferentes não devem
        esperar um pelo outro. Duas downloads lentas e concorrentes para
        tickers DIFERENTES devem terminar em ~1x o tempo de uma (paralelo),
        não ~2x (serializado por um lock global)."""

        def slow_download(*args, **kwargs):
            time.sleep(0.3)
            return _make_yf_df()

        barrier = threading.Barrier(2)
        results = [None, None]

        def worker(idx, ticker):
            barrier.wait()
            results[idx] = feed.fetch_recent_data(
                ticker, period="1d", interval="15m"
            )

        start = time.monotonic()
        with patch(
            "backend.app.data.feed.yf.download", side_effect=slow_download
        ):
            threads = [
                threading.Thread(target=worker, args=(0, "RENT3.SA")),
                threading.Thread(target=worker, args=(1, "SUZB3.SA")),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)
        elapsed = time.monotonic() - start

        assert results[0] is not None and results[1] is not None
        # Paralelo: ~0.3s. Serializado por engano: ~0.6s. Corta no meio.
        assert elapsed < 0.55, (
            f"Tickers diferentes bloquearam um ao outro: {elapsed:.2f}s "
            f"(esperado < 0.55s se locks são por chave)"
        )


class TestPriceCacheEviction:
    def test_evita_crescer_sem_teto_remove_mais_antigos_primeiro(self):
        # side_effect com factory: cada chamada do mock precisa de um
        # DataFrame NOVO — _fetch_from_yfinance faz reset_index(inplace=True),
        # então reusar o mesmo objeto (return_value=...) entre chamadas
        # corrompe a partir da 2ª (índice já resetado antes).
        with patch.object(feed, "PRICE_CACHE_MAX_ENTRIES", 3), patch(
            "backend.app.data.feed.yf.download", side_effect=lambda *a, **kw: _make_yf_df()
        ):
            for i in range(5):
                feed.fetch_recent_data(f"TICK{i}.SA", period="1d", interval="15m")

        assert len(feed._cache) <= 3
        # Os dois primeiros (mais antigos) devem ter sido evictados;
        # os três últimos devem sobreviver.
        chaves = list(feed._cache.keys())
        tickers_no_cache = {k[0] for k in chaves}
        assert "TICK0.SA" not in tickers_no_cache
        assert "TICK1.SA" not in tickers_no_cache
        assert "TICK4.SA" in tickers_no_cache


class TestFetchRecentDataRespectsExplicitTtl:
    """fetch_recent_data aceita um ttl explícito por chamada (P3-A Etapa
    2e) — o caminho de saída usa um TTL mais curto que o default, sem
    mudar o comportamento de quem não passa ttl (MarketAnalyst,
    get_current_price, get_candles continuam no PRICE_CACHE_TTL_SECONDS)."""

    def test_ttl_explicito_mais_curto_expira_antes_do_default(self):
        with patch.object(feed, "PRICE_CACHE_TTL_SECONDS", 100), patch(
            "backend.app.data.feed.yf.download",
            side_effect=lambda *a, **kw: _make_yf_df(),
        ) as mock_dl:
            feed.fetch_recent_data(
                "PETR4.SA", period="1d", interval="15m", ttl=0.05
            )
            time.sleep(0.12)
            # Com o default (100s) isso ainda seria HIT — só expira porque
            # o ttl explícito (0.05s) foi o que realmente valeu.
            feed.fetch_recent_data(
                "PETR4.SA", period="1d", interval="15m", ttl=0.05
            )

        assert mock_dl.call_count == 2

    def test_sem_ttl_explicito_usa_o_default_global(self):
        with patch.object(feed, "PRICE_CACHE_TTL_SECONDS", 100), patch(
            "backend.app.data.feed.yf.download",
            side_effect=lambda *a, **kw: _make_yf_df(),
        ) as mock_dl:
            feed.fetch_recent_data("VALE3.SA", period="5d", interval="15m")
            feed.fetch_recent_data("VALE3.SA", period="5d", interval="15m")

        assert mock_dl.call_count == 1  # dentro do default de 100s, HIT


class TestExitPriceCacheTtlDerivation:
    """P3-A Etapa 2e: TTL de saída = 2 × EXIT_INTERVAL_SECONDS, DERIVADO
    (não um número solto) — para que a fórmula do atraso de pior caso
    documentada em worker_state.py continue valendo mesmo se alguém mudar
    o intervalo do laço de saída."""

    def test_ttl_de_saida_e_multiplo_do_intervalo(self):
        """Propriedade geral: sem isso, o teto TTL+INTERVALO da fórmula
        documentada deixa de valer (vira TTL+INTERVALO-resto)."""
        ttl = worker_state.exit_price_cache_ttl_seconds()
        interval = worker_state.EXIT_INTERVAL_SECONDS
        assert ttl % interval == 0, (
            f"TTL de saída ({ttl}s) não é múltiplo do intervalo "
            f"({interval}s) — a fórmula do pior caso documentada quebra."
        )

    def test_ttl_de_saida_e_2x_o_intervalo(self):
        """Trava a decisão específica (2x), não só a divisibilidade geral —
        se o multiplicador mudar sem querer, isso pega."""
        assert (
            worker_state.exit_price_cache_ttl_seconds()
            == 2 * worker_state.EXIT_INTERVAL_SECONDS
        )

    def test_ttl_de_saida_acompanha_mudanca_no_intervalo(self):
        """DERIVADO de verdade: não pode ser um valor congelado que
        desalinha se EXIT_INTERVAL_SECONDS mudar depois (config futura,
        ou monkeypatch em outro teste)."""
        with patch.object(worker_state, "EXIT_INTERVAL_SECONDS", 7):
            assert worker_state.exit_price_cache_ttl_seconds() == 14

    def test_ttl_de_entrada_nao_foi_alterado(self):
        """Decisão explícita: TTL de entrada fica como está (15s) — não
        vale mexer só por estética se não muda comportamento."""
        assert feed.PRICE_CACHE_TTL_SECONDS == 15
