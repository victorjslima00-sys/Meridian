"""
Fixtures globais da suíte.

reset_price_cache (autouse): o cache de preço em backend/app/data/feed.py
(P3-A Etapa 2d) é estado em nível de módulo, compartilhado entre TODOS os
testes que chamam fetch_recent_data — sem reset entre casos, um teste que
popula o cache para (ticker, period, interval)=("BTC-USD","5d","1h") faz
outro teste que usa a MESMA chave (ex.: os defaults de fetch_recent_data)
receber um resultado "de graça" e nunca bater no mock de yf.download,
quebrando asserções de call_count de forma silenciosa e não-óbvia.

reset_alert_state (autouse): mesmo problema, outra estrutura — o estado de
deduplicação de alerta (backend/app/main.py::_last_alert_state) também é
um dict em nível de módulo, keyed por ticker. Descoberto na prática: dois
testes parametrizados de TestExitScanFailClosed reusam o ticker
"ITUB4.SA"; sem este reset, o alerta da 1ª iteração "gastava" a
deduplicação e as duas seguintes ficavam mudas — falso negativo bem
sutil, o alerta parecia ter sumido por bug quando na verdade era
contaminação entre testes.
"""
import pytest

from backend.app.data import feed


@pytest.fixture(autouse=True)
def reset_price_cache():
    with feed._cache_meta_lock:
        feed._cache.clear()
        feed._key_locks.clear()
    yield
    with feed._cache_meta_lock:
        feed._cache.clear()
        feed._key_locks.clear()


@pytest.fixture(autouse=True)
def reset_alert_state():
    from backend.app import main
    main._last_alert_state.clear()
    yield
    main._last_alert_state.clear()
