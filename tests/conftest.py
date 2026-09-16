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

reset_worker_state (autouse): terceiro caso da mesma classe de problema —
o singleton `state` (backend/app/worker_state.py) é global e, a partir da
Etapa 4, o portão único de entradas (_avaliar_portao_de_entradas) depende
dele em qualquer teste que chame _run_one_scan_cycle, mesmo fora de
tests/test_worker_supervision.py (que já tem seu próprio reset local —
redundante com este, sem problema, reset() é idempotente). Sem este
reset global, um teste que marca a saída saudável/sticky vaza pro
próximo teste do arquivo, ou de outro arquivo, que não esperava por isso.
"""
import pytest


@pytest.fixture
def synthetic_backtest_approval(monkeypatch):
    """Isolate cost/warmup unit tests from administrative review.

    Explicit opt-in for synthetic TESTE3.SA fixtures only. Real approval
    behavior is exercised separately in test_data_approval.py.
    """
    from trading_bot.signals import engine
    def synthetic_only(df, ticker, *args, **kwargs):
        if ticker != 'TESTE3.SA':
            raise ValueError('synthetic_fixture_only')
    monkeypatch.setattr(engine, 'require_data_approval', synthetic_only)

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


@pytest.fixture(autouse=True)
def reset_worker_state():
    from backend.app.worker_state import state
    state.reset()
    yield
    state.reset()


@pytest.fixture
def mock_circuit_breaker():
    from unittest.mock import patch
    with patch("trading_bot.risk.circuit_breaker.CircuitBreaker.can_trade", return_value=True):
        yield



@pytest.fixture(autouse=True)
def mock_validate_dataset_digest(monkeypatch, request):
    if (
        'test_data_approval' in request.module.__name__
        or 'test_nexus_002' in request.module.__name__
        or 'test_nexus_003' in request.module.__name__
        or 'sem_aprovacao' in request.node.name
    ):
        return
    import trading_bot.data.approval
    from trading_bot.data.approval import Approval, Evidence, compute_candidate_id

    def _mock_require(digest, *args, **kwargs):
        if digest == 'invalid_hash':
            raise ValueError('data_approval_required')
        ev = Evidence(path="dummy.csv", sha256="0" * 64)
        c_id = compute_candidate_id(
            ticker="PETR4.SA",
            strategy_id="donchian_breakout",
            intended_use="PAPER_TRADING",
            dataset_sha256=digest,
            collected_at_utc="2026-09-16T12:00:00Z",
            dataset_artifact_sha256=ev.sha256,
            review_csv_sha256=ev.sha256,
            source_sha256=ev.sha256,
            calendar_sha256=ev.sha256,
            adjustments_sha256=ev.sha256,
            point_in_time_sha256=ev.sha256,
        )
        return Approval(
            candidate_id=c_id,
            ticker="PETR4.SA",
            strategy_id="donchian_breakout",
            intended_use="PAPER_TRADING",
            dataset_sha256=digest,
            collected_at_utc="2026-09-16T12:00:00Z",
            dataset_artifact=ev,
            review_csv=ev,
            source=ev,
            calendar=ev,
            adjustments=ev,
            point_in_time=ev,
            reviewed_by="test-mock",
            review_notes="mocked for test",
            status="approved",
        )

    def _mock_validate(digest, *args, **kwargs):
        _mock_require(digest, *args, **kwargs)

    monkeypatch.setattr(trading_bot.data.approval, 'validate_dataset_digest', _mock_validate)
    monkeypatch.setattr(trading_bot.data.approval, 'require_dataset_approval_by_digest', _mock_require)

