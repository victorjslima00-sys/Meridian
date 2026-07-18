"""
P3-A Etapa 2 — split de laços (latência de stop-loss).
=========================================================
Sub-etapa 2a: _run_exit_scan() e _price_is_trustworthy(), isoladas — ainda
não ligadas a nenhum loop em produção (isso é 2b).

_run_exit_scan() varre SÓ tickers com status='active' (custo independe do
tamanho do universo, ao contrário do laço lento que varre todo mundo a
cada ciclo — ver BACKLOG.md). _price_is_trustworthy() é o gate FAIL-CLOSED:
preço não confiável nunca decide nada sobre a posição, só mantém como está.

Sub-etapa 2b: PHASE 1 sai do laço lento (_run_one_scan_cycle) — a gestão de
saídas passa a ser 100% do exit_loop/_run_exit_scan. Isso remove, de
brinde, o `continue` que impedia (como efeito colateral) o laço lento de
tentar abrir uma segunda posição num ticker já ativo. TestSlowLoopSkipsAlreadyActiveTicker
cobre essa regressão com uma guarda explícita nova.
"""
import math
import os
import sqlite3
import tempfile
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from backend.app.data import database as database_module


def _make_price_row(close, open_=None, high=None, low=None):
    """DataFrame de 1 linha, no formato retornado por fetch_recent_data
    (colunas minúsculas: open/high/low/close/volume/date)."""
    if open_ is None:
        open_ = close
    if high is None:
        high = close
    if low is None:
        low = close
    return pd.DataFrame({
        "open": [open_], "high": [high], "low": [low], "close": [close],
        "volume": [1000], "date": [datetime.now()],
    })


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    original_path = database_module.DB_PATH
    database_module.DB_PATH = path
    try:
        database_module.init_db()
    finally:
        database_module.DB_PATH = original_path
    yield path
    os.unlink(path)


def _insert_active_trade(path, ticker, side, entry_price, target_price, stop_loss):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, target_price, "
        "stop_loss, entry_date, ai_rationale, status) VALUES (?,?,?,?,?,?,?,?,?)",
        (ticker, side, 1.0, entry_price, target_price, stop_loss,
         datetime.now(), "t", "active"),
    )
    conn.commit()
    trade_id = conn.execute("SELECT MAX(id) FROM trades").fetchone()[0]
    conn.close()
    return trade_id


def _insert_closed_trade(path, ticker):
    """Histórico de ticker já fechado — simula 'universo grande' sem
    posição ativa alguma; não deve ser tocado pelo exit scan."""
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, exit_price, "
        "target_price, stop_loss, entry_date, exit_date, ai_rationale, status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (ticker, "BUY", 1.0, 10.0, 11.0, 12.0, 9.0,
         datetime.now(), datetime.now(), "t", "closed"),
    )
    conn.commit()
    conn.close()


def _trade_status(path, trade_id):
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT status FROM trades WHERE id = ?", (trade_id,)).fetchone()
    conn.close()
    return row[0] if row else None


class TestPriceIsTrustworthy:
    """Unitários, sem DB — só a lógica de gate fail-closed."""

    def test_preco_valido_e_confiavel(self):
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy(35.50) is True

    def test_none_nao_e_confiavel(self):
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy(None) is False

    def test_zero_nao_e_confiavel(self):
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy(0.0) is False

    def test_negativo_nao_e_confiavel(self):
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy(-5.0) is False

    def test_nan_nao_e_confiavel(self):
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy(math.nan) is False

    def test_string_nao_numerica_nao_e_confiavel(self):
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy("indisponivel") is False

    def test_ohlc_zerado_nao_e_confiavel_mesmo_com_close_valido(self):
        """Artefato conhecido do yfinance: candle do dia corrente com
        Open/High/Low zerados (ver patch cosmético em get_candles) — mesmo
        que o close pareça válido, o candle é dado incompleto."""
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy(35.50, open_=0.0, high=0.0, low=0.0) is False

    def test_ohlc_valido_e_confiavel(self):
        from backend.app.main import _price_is_trustworthy
        assert _price_is_trustworthy(35.50, open_=35.0, high=36.0, low=34.5) is True


class TestRunExitScan:
    async def test_exit_scan_touches_only_active_tickers_and_reacts_immediately(
        self, temp_db_path
    ):
        """Universo grande (50 tickers com histórico fechado) + 1 posição
        ativa no stop. O scan deve tocar SÓ o ticker ativo (custo não
        escala com o universo) e fechar a posição numa única passada —
        não precisa esperar um 'ciclo completo' como o laço lento."""
        for i in range(50):
            _insert_closed_trade(temp_db_path, f"TICKER{i}.SA")

        trade_id = _insert_active_trade(
            temp_db_path, "PETR4.SA", "BUY",
            entry_price=30.0, target_price=40.0, stop_loss=28.0,
        )

        df = _make_price_row(close=27.5)  # abaixo do stop_loss=28.0

        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            with patch(
                "backend.app.data.feed.fetch_recent_data",
            ) as mock_fetch, \
                 patch("backend.app.main.ExecutorAgent") as MockExecutor:
                mock_fetch.return_value = df
                mock_executor_instance = MockExecutor.return_value
                mock_executor_instance.close_order.return_value = {
                    "status": "closed", "pnl_pct": -8.3
                }

                from backend.app.main import _run_exit_scan
                await _run_exit_scan()
        finally:
            database_module.DB_PATH = original_path

        # Só o ticker ativo foi consultado, nunca os 50 do "universo".
        assert mock_fetch.call_count == 1
        called_ticker = mock_fetch.call_args[0][0]
        assert called_ticker == "PETR4.SA"

        # Fechado numa única passada do scan (stop batido).
        mock_executor_instance.close_order.assert_called_once()
        args = mock_executor_instance.close_order.call_args[0]
        assert args[0] == trade_id
        assert args[1] == 27.5

    async def test_exit_scan_ignores_tickers_without_active_position(
        self, temp_db_path
    ):
        _insert_closed_trade(temp_db_path, "VALE3.SA")

        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            with patch(
                "backend.app.data.feed.fetch_recent_data",
            ) as mock_fetch:
                from backend.app.main import _run_exit_scan
                await _run_exit_scan()
        finally:
            database_module.DB_PATH = original_path

        mock_fetch.assert_not_called()


class TestExitScanFailClosed:
    @pytest.mark.parametrize("bad_price", [None, 0.0, math.nan])
    async def test_nao_fecha_posicao_com_preco_nao_confiavel(
        self, temp_db_path, bad_price
    ):
        """Posição no stop, mas o feed devolve preço lixo: a posição deve
        permanecer ativa (fail-closed = não agir, nunca 'vender por
        precaução'), close_order nunca é chamado, e um alerta é disparado."""
        trade_id = _insert_active_trade(
            temp_db_path, "ITUB4.SA", "BUY",
            entry_price=30.0, target_price=40.0, stop_loss=28.0,
        )

        df = _make_price_row(close=bad_price)

        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            with patch(
                "backend.app.data.feed.fetch_recent_data",
            ) as mock_fetch, \
                 patch("backend.app.main.ExecutorAgent") as MockExecutor, \
                 patch("backend.app.main._alerta_telegram") as mock_alerta:
                mock_fetch.return_value = df

                from backend.app.main import _run_exit_scan
                await _run_exit_scan()
        finally:
            database_module.DB_PATH = original_path

        MockExecutor.return_value.close_order.assert_not_called()
        assert _trade_status(temp_db_path, trade_id) == "active"
        assert mock_alerta.called

    async def test_ohlc_zerado_tambem_nao_fecha(self, temp_db_path):
        trade_id = _insert_active_trade(
            temp_db_path, "BBDC4.SA", "BUY",
            entry_price=30.0, target_price=40.0, stop_loss=28.0,
        )
        # close "parece" válido, mas open/high/low zerados = candle incompleto
        df = _make_price_row(close=27.0, open_=0.0, high=0.0, low=0.0)

        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            with patch(
                "backend.app.data.feed.fetch_recent_data",
            ) as mock_fetch, \
                 patch("backend.app.main.ExecutorAgent") as MockExecutor, \
                 patch("backend.app.main._alerta_telegram"):
                mock_fetch.return_value = df

                from backend.app.main import _run_exit_scan
                await _run_exit_scan()
        finally:
            database_module.DB_PATH = original_path

        MockExecutor.return_value.close_order.assert_not_called()
        assert _trade_status(temp_db_path, trade_id) == "active"


class _FakeAppConfig:
    """Substitui AppConfig.load() com um universo pequeno e controlado,
    sem depender do config/settings.yaml + universe.yaml reais (50 tickers
    de verdade), que não são o que este teste de regressão quer exercitar."""

    def __init__(self, tickers):
        self._tickers = tickers

    def get(self, *keys, default=None):
        if keys == ("_universe", "tickers"):
            return self._tickers
        return default


class TestSlowLoopSkipsAlreadyActiveTicker:
    """Regressão (P3-A Etapa 2b): removida a PHASE 1 do laço lento, o
    `continue` que barrava (como efeito colateral) entrada duplicada num
    ticker já posicionado também some. Sem uma guarda explícita nova, o
    laço lento tentaria abrir uma segunda posição, e só o índice único
    (P3-A Etapa 1) barraria — com IntegrityError em vez de comportamento
    correto, que é o que o plano original queria evitar.

    MarketAnalyst é mockado na CLASSE (não só ExecutorAgent): a asserção
    forte é que o ticker já ativo nem chega a ser analisado — a guarda
    pula ANTES da análise, não só antes da execução.
    """

    async def test_ticker_ja_ativo_e_pulado_sem_chamar_market_analyst(
        self, temp_db_path
    ):
        _insert_active_trade(
            temp_db_path, "AAAA.SA", "BUY",
            entry_price=10.0, target_price=12.0, stop_loss=9.0,
        )

        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            from backend.app import main

            fake_cfg = _FakeAppConfig(["AAAA", "BBBB"])
            fake_breaker = MagicMock()
            fake_breaker.can_trade.return_value = True

            with patch(
                "trading_bot.core.config.AppConfig.load", return_value=fake_cfg
            ), \
                 patch(
                     "trading_bot.risk.circuit_breaker.CircuitBreaker.from_config",
                     return_value=fake_breaker,
                 ), \
                 patch.object(main, "has_snapshot_for", return_value=True), \
                 patch.object(main, "MarketAnalyst") as MockAnalyst, \
                 patch.object(main, "ExecutorAgent") as MockExecutor, \
                 patch(
                     "backend.app.data.feed.fetch_recent_data",
                     return_value=_make_price_row(close=10.5),
                 ):
                # Nota: este mock de fetch_recent_data só é necessário
                # enquanto a PHASE 1 ainda existir no laço lento (o fetch de
                # topo que ela usa) — em 2b esse fetch é removido por ser
                # código morto (MarketAnalyst busca seus próprios dados).

                MockAnalyst.return_value.analyze = AsyncMock(
                    return_value={"signal": "HOLD", "reason": "sem sinal"}
                )

                await main._run_one_scan_cycle()
        finally:
            database_module.DB_PATH = original_path

        # AAAA.SA já tem posição ativa: nem deve ser instanciado o analyst
        # para ele. BBBB.SA (livre) deve ser analisado normalmente.
        analisados = [c.args[0] for c in MockAnalyst.call_args_list]
        assert "AAAA.SA" not in analisados
        assert "BBBB.SA" in analisados

        # Nunca tentou abrir uma segunda posição no ticker já ativo.
        MockExecutor.return_value.execute_order.assert_not_called()


class TestAlertDeduplication:
    """P3-A Etapa 2d: exit_loop roda a cada ~5s. Sem deduplicação, uma
    condição de preço não confiável PERSISTENTE (não só rate limit
    transitório) dispararia um alerta Telegram a cada iteração — alarme
    que grita sem parar vira alarme ignorado (já errado 2x nisso, ver
    histórico do BACKLOG). Alerta na primeira ocorrência, silencia
    repetições da mesma condição, reenvia um lembrete após o cooldown com
    o problema ainda ativo (nunca silêncio total — CLAUDE.md).

    Reset de _last_alert_state é global, via tests/conftest.py — não
    local aqui (esse dict também é usado, e pode ser sujado, por outras
    classes deste arquivo, ex.: TestExitScanFailClosed)."""

    def test_primeira_ocorrencia_alerta(self):
        from backend.app import main
        assert main._should_alert_price_untrustworthy("PETR4.SA", "untrustworthy_price") is True

    def test_segunda_ocorrencia_imediata_nao_realerta(self):
        from backend.app import main
        assert main._should_alert_price_untrustworthy("PETR4.SA", "untrustworthy_price") is True
        assert main._should_alert_price_untrustworthy("PETR4.SA", "untrustworthy_price") is False
        assert main._should_alert_price_untrustworthy("PETR4.SA", "untrustworthy_price") is False

    def test_ticker_diferente_alerta_independente(self):
        from backend.app import main
        assert main._should_alert_price_untrustworthy("PETR4.SA", "untrustworthy_price") is True
        assert main._should_alert_price_untrustworthy("VALE3.SA", "untrustworthy_price") is True

    def test_mudanca_de_estado_apos_recuperacao_realerta(self):
        from backend.app import main
        assert main._should_alert_price_untrustworthy("PETR4.SA", "untrustworthy_price") is True
        assert main._should_alert_price_untrustworthy("PETR4.SA", "untrustworthy_price") is False
        main._clear_alert_state("PETR4.SA")  # preço voltou a ser confiável
        assert main._should_alert_price_untrustworthy("PETR4.SA", "untrustworthy_price") is True

    def test_cooldown_expirado_com_problema_ativo_realerta(self):
        from backend.app import main
        with patch.object(main, "ALERT_COOLDOWN_SECONDS", 0.05):
            assert main._should_alert_price_untrustworthy("PETR4.SA", "untrustworthy_price") is True
            assert main._should_alert_price_untrustworthy("PETR4.SA", "untrustworthy_price") is False
            time.sleep(0.12)
            assert main._should_alert_price_untrustworthy("PETR4.SA", "untrustworthy_price") is True

    async def test_run_exit_scan_nao_realerta_em_scans_consecutivos_com_preco_ruim(
        self, temp_db_path
    ):
        """Integração: duas chamadas seguidas de _run_exit_scan com o
        mesmo preço inválido persistente devem gerar 1 alerta, não 2."""
        _insert_active_trade(
            temp_db_path, "HAPV3.SA", "BUY",
            entry_price=30.0, target_price=40.0, stop_loss=28.0,
        )
        df_ruim = _make_price_row(close=None)

        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            with patch(
                "backend.app.data.feed.fetch_recent_data", return_value=df_ruim
            ), \
                 patch("backend.app.main.ExecutorAgent"), \
                 patch("backend.app.main._alerta_telegram") as mock_alerta:
                from backend.app.main import _run_exit_scan
                await _run_exit_scan()
                await _run_exit_scan()
        finally:
            database_module.DB_PATH = original_path

        assert mock_alerta.call_count == 1

    async def test_run_exit_scan_realerta_apos_recuperacao_e_nova_falha(
        self, temp_db_path
    ):
        """Preço ruim -> alerta. Preço bom -> sem alerta, estado limpo.
        Preço ruim de novo -> alerta de novo (condição nova, não repetição)."""
        _insert_active_trade(
            temp_db_path, "FLRY3.SA", "BUY",
            entry_price=30.0, target_price=40.0, stop_loss=28.0,
        )
        df_ruim = _make_price_row(close=None)
        df_bom = _make_price_row(close=32.0)  # entre stop e target, não fecha

        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            with patch("backend.app.main.ExecutorAgent"), \
                 patch("backend.app.main._alerta_telegram") as mock_alerta:
                from backend.app.main import _run_exit_scan

                with patch(
                    "backend.app.data.feed.fetch_recent_data", return_value=df_ruim
                ):
                    await _run_exit_scan()  # 1º alerta

                with patch(
                    "backend.app.data.feed.fetch_recent_data", return_value=df_bom
                ):
                    await _run_exit_scan()  # recupera, sem alerta

                with patch(
                    "backend.app.data.feed.fetch_recent_data", return_value=df_ruim
                ):
                    await _run_exit_scan()  # 2º alerta (condição nova)
        finally:
            database_module.DB_PATH = original_path

        assert mock_alerta.call_count == 2


class TestExitScanUsesDerivedTtl:
    """P3-A Etapa 2e: _run_exit_scan deve passar o TTL derivado
    (worker_state.exit_price_cache_ttl_seconds()) para fetch_recent_data,
    não confiar no default global do cache (que é o TTL de ENTRADA)."""

    async def test_run_exit_scan_passa_ttl_derivado_para_fetch(self, temp_db_path):
        from backend.app import worker_state

        _insert_active_trade(
            temp_db_path, "PETR4.SA", "BUY",
            entry_price=30.0, target_price=40.0, stop_loss=28.0,
        )
        df = _make_price_row(close=32.0)  # entre stop e target, não fecha

        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            with patch(
                "backend.app.data.feed.fetch_recent_data", return_value=df
            ) as mock_fetch:
                from backend.app.main import _run_exit_scan
                await _run_exit_scan()
        finally:
            database_module.DB_PATH = original_path

        mock_fetch.assert_called_once()
        _, kwargs = mock_fetch.call_args
        assert kwargs.get("ttl") == worker_state.exit_price_cache_ttl_seconds()


class TestRunExitScanEffectiveness:
    """P3-A Etapa 3 (heartbeat granular): _run_exit_scan retorna True se a
    passada foi PLENAMENTE efetiva — todo ticker ativo teve preço
    confiável avaliado, ou não havia nenhum ticker ativo (nada podia ter
    ficado desprotegido). Retorna False se ao menos UM ticker ativo teve
    preço não confiável nesta passada, mesmo que outros tenham sido
    avaliados normalmente — o sinal é sobre a saúde do sistema como um
    todo, não sobre um ticker isolado (esse já tem seu próprio alerta,
    deduplicado, desde a Etapa 2d)."""

    async def test_zero_posicoes_ativas_e_efetiva(self, temp_db_path):
        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            from backend.app.main import _run_exit_scan
            resultado = await _run_exit_scan()
        finally:
            database_module.DB_PATH = original_path

        assert resultado is True

    async def test_tres_ativas_todas_com_preco_confiavel_e_efetiva(
        self, temp_db_path
    ):
        _insert_active_trade(
            temp_db_path, "AAAA.SA", "BUY",
            entry_price=10.0, target_price=20.0, stop_loss=5.0,
        )
        _insert_active_trade(
            temp_db_path, "BBBB.SA", "BUY",
            entry_price=10.0, target_price=20.0, stop_loss=5.0,
        )
        _insert_active_trade(
            temp_db_path, "CCCC.SA", "BUY",
            entry_price=10.0, target_price=20.0, stop_loss=5.0,
        )

        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            with patch(
                "backend.app.data.feed.fetch_recent_data",
                return_value=_make_price_row(close=12.0),
            ), patch("backend.app.main.ExecutorAgent"):
                from backend.app.main import _run_exit_scan
                resultado = await _run_exit_scan()
        finally:
            database_module.DB_PATH = original_path

        assert resultado is True

    async def test_uma_de_tres_com_preco_ruim_nao_e_efetiva(self, temp_db_path):
        """Mesmo com 2 avaliações boas, 1 ruim já torna a passada
        NÃO efetiva — o sinal agregado não pode esconder uma posição
        que ficou sem avaliação."""
        _insert_active_trade(
            temp_db_path, "AAAA.SA", "BUY",
            entry_price=10.0, target_price=20.0, stop_loss=5.0,
        )
        _insert_active_trade(
            temp_db_path, "BBBB.SA", "BUY",
            entry_price=10.0, target_price=20.0, stop_loss=5.0,
        )
        _insert_active_trade(
            temp_db_path, "CCCC.SA", "BUY",
            entry_price=10.0, target_price=20.0, stop_loss=5.0,
        )

        def fetch_side_effect(ticker, *args, **kwargs):
            if ticker == "BBBB.SA":
                return _make_price_row(close=None)  # preço ruim só para este
            return _make_price_row(close=12.0)

        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            with patch(
                "backend.app.data.feed.fetch_recent_data",
                side_effect=fetch_side_effect,
            ), patch("backend.app.main.ExecutorAgent"), patch(
                "backend.app.main._alerta_telegram"
            ):
                from backend.app.main import _run_exit_scan
                resultado = await _run_exit_scan()
        finally:
            database_module.DB_PATH = original_path

        assert resultado is False
