import time
import logging
import threading
from collections import OrderedDict
from typing import Optional, Tuple

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

# Crypto tickers que não precisam do sufixo .SA
_CRYPTO_TICKERS = {"BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "ADA-USD"}
_PASSTHROUGH_TICKERS = {"^BVSP", "BRL=X", "SPY", "QQQ"}


def _normalize_ticker(ticker: str) -> str:
    """Adiciona sufixo .SA para ações B3 quando necessário."""
    if ticker in _CRYPTO_TICKERS or ticker in _PASSTHROUGH_TICKERS:
        return ticker
    if not ticker.endswith(".SA") and len(ticker) >= 4 and ticker[-1].isdigit():
        return f"{ticker}.SA"
    return ticker


# -----------------------------------------------------------------------
# Cache de preço (P3-A Etapa 2d)
# -----------------------------------------------------------------------
# Compartilhado por todo mundo que chama fetch_recent_data (exit_loop,
# MarketAnalyst, get_current_price, get_candles): sem isso, N posições
# ativas em exit_loop geram N requisições de rede a cada
# EXIT_INTERVAL_SECONDS (~5s) — com poucas posições simultâneas já se bate
# no rate limit que este projeto mediu empiricamente (ver BACKLOG.md: gaps
# de ~11s já apareciam com ~12 req/min sustentado, MENOS do que N=1
# posição ativa gera sozinha no intervalo atual). O cache desacopla a taxa
# de rede do número de chamadores: no máximo 1 requisição de rede por
# chave (ticker, period, interval) por janela de TTL, não importa quantos
# "laços" pedem a mesma coisa quase ao mesmo tempo.
#
# fetch_recent_data roda em THREADS REAIS via asyncio.to_thread, não em
# corrotinas — os dois laços (exit_loop e o laço lento de entradas) podem
# estar literalmente dentro desta função ao mesmo tempo, em threads do SO
# diferentes. Por isso os locks aqui são threading.Lock, não asyncio.Lock
# (que só serializa corrotinas agendadas no event loop — não tem efeito
# nenhum sobre concorrência real entre threads de um ThreadPoolExecutor).
#
# Lock POR CHAVE, não um lock único global: um lock global serializaria
# até buscas de tickers DIFERENTES sem necessidade nenhuma (ver
# TestPriceCacheConcurrency.test_tickers_diferentes_concorrentes_nao_se_bloqueiam_por_um_lock_global).
# Cada chave ganha seu próprio threading.Lock, criado sob demanda; um
# meta-lock curto (_cache_meta_lock) protege só a estrutura dos dicts
# (_cache, _key_locks) em si — nunca é mantido durante a chamada de rede,
# que é a parte lenta.
PRICE_CACHE_TTL_SECONDS = 15    # tests podem monkeypatchar
PRICE_CACHE_MAX_ENTRIES = 200   # ~50 tickers × combinações (period, interval) usadas no código

_cache_meta_lock = threading.Lock()
_cache: "OrderedDict[Tuple[str, str, str], Tuple[float, pd.DataFrame]]" = OrderedDict()
_key_locks: dict = {}


def _cache_key(ticker: str, period: str, interval: str) -> Tuple[str, str, str]:
    return (ticker, period, interval)


def _cache_get(key: Tuple[str, str, str], ttl: float) -> Optional[pd.DataFrame]:
    """None se não há entrada válida (ausente OU expirada pelo TTL).
    Sempre retorna uma CÓPIA — nunca a referência interna — para que uma
    mutação do chamador não corrompa o cache nem vaze para outro chamador
    que peça a mesma chave depois. `ttl` é decidido pelo CHAMADOR de
    fetch_recent_data a cada leitura — não fica gravado junto da entrada —
    então o mesmo dado pode ser considerado "fresco o bastante" por um
    caminho e "velho demais" por outro sem nenhum conflito."""
    with _cache_meta_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        fetched_at, df = entry
        if time.monotonic() - fetched_at > ttl:
            return None
        return df.copy()


def _cache_put(key: Tuple[str, str, str], df: pd.DataFrame) -> None:
    """Só é chamada com um resultado BEM-SUCEDIDO — ver fetch_recent_data.
    Uma falha nunca vira entrada de cache: se cacheássemos o "não sei",
    um erro transitório de rede ficaria congelado até o TTL expirar,
    quando o certo é deixar a PRÓXIMA chamada tentar de novo.

    Evicção FIFO por ordem de escrita quando PRICE_CACHE_MAX_ENTRIES é
    excedido — o universo tem ~50 tickers hoje, mas nada garante isso pra
    sempre; sem teto, o cache cresceria sem limite se o universo mudar."""
    with _cache_meta_lock:
        _cache[key] = (time.monotonic(), df.copy())
        _cache.move_to_end(key)
        while len(_cache) > PRICE_CACHE_MAX_ENTRIES:
            oldest_key, _ = _cache.popitem(last=False)
            # Nunca remove um lock que está em uso (fetch em andamento para
            # aquela chave) — só limpa locks já ociosos.
            lock = _key_locks.get(oldest_key)
            if lock is not None and not lock.locked():
                del _key_locks[oldest_key]


def _get_key_lock(key: Tuple[str, str, str]) -> threading.Lock:
    with _cache_meta_lock:
        lock = _key_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _key_locks[key] = lock
        return lock


def fetch_recent_data(
    ticker: str, period: str = "5d", interval: str = "1h", max_retries: int = 3,
    ttl: Optional[float] = None,
):
    """
    Busca dados OHLCV recentes usando yfinance, com cache curto compartilhado
    (ver seção "Cache de preço" acima) e retry com backoff exponencial para
    tolerância a falhas de rede.

    Args:
        ticker:      Ticker do ativo (ex: "BTC-USD", "PETR4")
        period:      Período de histórico (ex: "5d", "1mo")
        interval:    Intervalo dos candles (ex: "15m", "1h", "1d")
        max_retries: Número máximo de tentativas antes de desistir
        ttl:         TTL específico (segundos) para ESTA chamada. Se None
                     (default), usa PRICE_CACHE_TTL_SECONDS. Caminhos com
                     necessidade de frescor diferente do padrão (ex.:
                     exit_loop — ver worker_state.exit_price_cache_ttl_seconds())
                     passam um valor explícito; quem não passa nada mantém
                     o comportamento de sempre.

    Returns:
        DataFrame normalizado (cópia independente, segura para o chamador
        mutar) ou None em caso de falha total. Falha NUNCA é cacheada.
    """
    normalized = _normalize_ticker(ticker)
    key = _cache_key(normalized, period, interval)
    effective_ttl = ttl if ttl is not None else PRICE_CACHE_TTL_SECONDS

    cached = _cache_get(key, effective_ttl)
    if cached is not None:
        return cached

    lock = _get_key_lock(key)
    with lock:
        # Double-checked locking: enquanto esperávamos este lock, outra
        # thread pode ter terminado de buscar (e cacheado) a mesma chave —
        # é exatamente isso que colapsa duas requisições concorrentes em
        # uma só chamada de rede.
        cached = _cache_get(key, effective_ttl)
        if cached is not None:
            return cached

        df = _fetch_from_yfinance(normalized, period, interval, max_retries)
        if df is not None:
            _cache_put(key, df)
            return df.copy()
        return None


def _fetch_from_yfinance(
    normalized: str, period: str, interval: str, max_retries: int
) -> Optional[pd.DataFrame]:
    """Busca de verdade no yfinance, com retry + backoff exponencial.
    Isolada de fetch_recent_data para que o cache decida SE isto é
    chamado, sem se misturar com COMO a busca em si funciona."""
    for attempt in range(max_retries):
        try:
            df = yf.download(
                normalized,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
            )

            if df is None or df.empty:
                logger.warning(
                    "[%s] Dados vazios (tentativa %d/%d)",
                    normalized,
                    attempt + 1,
                    max_retries,
                )
                if attempt < max_retries - 1:
                    time.sleep(2**attempt)
                continue

            # Normalizar índice e colunas
            df.reset_index(inplace=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            df.rename(columns={"Datetime": "date", "Date": "date"}, inplace=True)
            df.columns = [c.lower() for c in df.columns]

            logger.debug(
                "[%s] %d candles carregados (period=%s interval=%s)",
                normalized,
                len(df),
                period,
                interval,
            )
            return df

        except Exception as e:
            wait = 2**attempt
            logger.warning(
                "[%s] Erro na tentativa %d/%d: %s. Aguardando %ds...",
                normalized,
                attempt + 1,
                max_retries,
                e,
                wait,
            )
            if attempt < max_retries - 1:
                time.sleep(wait)

    logger.error("[%s] Falha total após %d tentativas.", normalized, max_retries)
    return None


def get_current_price(ticker: str) -> float:
    """Retorna o preço mais recente do ativo. Retorna 0.0 em caso de falha."""
    df = fetch_recent_data(ticker, period="1d", interval="1m")
    if df is not None and not df.empty:
        return float(df.iloc[-1]["close"])
    return 0.0
