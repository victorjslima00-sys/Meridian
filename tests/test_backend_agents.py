"""
Tests for the Backend AI Committee Agents
==========================================
Covers: MarketAnalyst (Gemini LLM), RiskManager (Kelly + Correlation), ExecutorAgent (open/close).
Uses AsyncMock to avoid real HTTP calls and in-memory SQLite for DB operations.
"""
import json
import sqlite3
import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_price_df(n=30, start=100.0, end=130.0) -> pd.DataFrame:
    prices = np.linspace(start, end, n)
    df = pd.DataFrame({
        "close": prices, "open": prices * 0.99,
        "high": prices * 1.01, "low": prices * 0.98,
        "volume": [1_000_000] * n,
        "date": pd.date_range("2024-01-01", periods=n, freq="15min"),
    })
    return df


def _make_downtrend_df(n=30) -> pd.DataFrame:
    return _make_price_df(n, start=130.0, end=100.0)


def _mock_llm_response(signal: str, reason: str = "Test reason") -> MagicMock:
    r = MagicMock()
    r.content = json.dumps({"signal": signal, "reason": reason})
    return r


def _init_in_memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, side TEXT, shares REAL, entry_price REAL,
            exit_price REAL, target_price REAL, stop_loss REAL,
            entry_date TIMESTAMP, exit_date TIMESTAMP,
            pnl_pct REAL, exit_reason TEXT, ai_rationale TEXT, status TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patrimonio_total REAL DEFAULT 0.0,
            saldo_disponivel REAL DEFAULT 100.0,
            em_posicoes REAL DEFAULT 0.0,
            updated_at TIMESTAMP
        )
    """)
    conn.execute(
        "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, updated_at) "
        "VALUES (0.0, 100.0, 0.0, ?)", (datetime.now(),)
    )
    conn.commit()
    return conn


# ============================================================================
# MARKET ANALYST TESTS
# ============================================================================

class TestMarketAnalyst:

    @pytest.mark.asyncio
    async def test_returns_buy_on_uptrend_with_gemini(self):
        from backend.app.agents.market_analyst import MarketAnalyst
        mock_resp = _mock_llm_response("BUY", "SMA10 cruzou SMA20 para cima")
        with patch("backend.app.agents.market_analyst.fetch_recent_data",
                   return_value=_make_price_df()), \
             patch("backend.app.agents.market_analyst.ResilientLLMClient") as MockLLM:
            MockLLM.return_value.generate_text_async = AsyncMock(return_value=mock_resp)
            result = await MarketAnalyst("BTC-USD").analyze()
        assert result["signal"] == "BUY"
        assert result["last_price"] > 0

    @pytest.mark.asyncio
    async def test_returns_sell_on_downtrend_with_gemini(self):
        from backend.app.agents.market_analyst import MarketAnalyst
        mock_resp = _mock_llm_response("SELL", "Downtrend confirmado")
        with patch("backend.app.agents.market_analyst.fetch_recent_data",
                   return_value=_make_downtrend_df()), \
             patch("backend.app.agents.market_analyst.ResilientLLMClient") as MockLLM:
            MockLLM.return_value.generate_text_async = AsyncMock(return_value=mock_resp)
            result = await MarketAnalyst("ETH-USD").analyze()
        assert result["signal"] == "SELL"

    @pytest.mark.asyncio
    async def test_fallback_to_math_when_llm_returns_none(self):
        from backend.app.agents.market_analyst import MarketAnalyst
        with patch("backend.app.agents.market_analyst.fetch_recent_data",
                   return_value=_make_price_df()), \
             patch("backend.app.agents.market_analyst.ResilientLLMClient") as MockLLM:
            MockLLM.return_value.generate_text_async = AsyncMock(return_value=None)
            result = await MarketAnalyst("BTC-USD").analyze()
        assert result["signal"] == "BUY"
        assert "Fallback" in result["reason"]

    @pytest.mark.asyncio
    async def test_fallback_to_math_when_llm_returns_invalid_json(self):
        from backend.app.agents.market_analyst import MarketAnalyst
        bad_resp = MagicMock()
        bad_resp.content = "isso nao e json"
        with patch("backend.app.agents.market_analyst.fetch_recent_data",
                   return_value=_make_price_df()), \
             patch("backend.app.agents.market_analyst.ResilientLLMClient") as MockLLM:
            MockLLM.return_value.generate_text_async = AsyncMock(return_value=bad_resp)
            result = await MarketAnalyst("BTC-USD").analyze()
        assert result["signal"] in ["BUY", "SELL", "HOLD"]
        assert "Fallback" in result["reason"]

    @pytest.mark.asyncio
    async def test_returns_hold_on_insufficient_data(self):
        from backend.app.agents.market_analyst import MarketAnalyst
        with patch("backend.app.agents.market_analyst.fetch_recent_data",
                   return_value=_make_price_df(n=5)), \
             patch("backend.app.agents.market_analyst.ResilientLLMClient") as MockLLM:
            MockLLM.return_value.generate_text_async = AsyncMock()
            result = await MarketAnalyst("SOL-USD").analyze()
        assert result["signal"] == "HOLD"
        MockLLM.return_value.generate_text_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_hold_on_no_data(self):
        from backend.app.agents.market_analyst import MarketAnalyst
        with patch("backend.app.agents.market_analyst.fetch_recent_data", return_value=None):
            result = await MarketAnalyst("BTC-USD").analyze()
        assert result["signal"] == "HOLD"

    @pytest.mark.asyncio
    async def test_sanitizes_invalid_signal_from_llm(self):
        from backend.app.agents.market_analyst import MarketAnalyst
        bad_signal = MagicMock()
        bad_signal.content = '{"signal": "LONG", "reason": "Resposta inesperada"}'
        with patch("backend.app.agents.market_analyst.fetch_recent_data",
                   return_value=_make_price_df()), \
             patch("backend.app.agents.market_analyst.ResilientLLMClient") as MockLLM:
            MockLLM.return_value.generate_text_async = AsyncMock(return_value=bad_signal)
            result = await MarketAnalyst("BTC-USD").analyze()
        assert result["signal"] == "HOLD"


# ============================================================================
# RISK MANAGER TESTS
# ============================================================================

class TestRiskManager:

    def test_approves_trade_with_sufficient_capital(self):
        from backend.app.agents.risk_manager import RiskManager
        result = RiskManager(saldo_livre=1000.0).evaluate_trade(
            {
                "signal": "BUY", 
                "last_price": 50000.0,
                "target_price": 55000.0,
                "stop_loss": 48000.0,
                "confidence": 70
            }, 
            ticker="BTC-USD", 
            open_tickers=[]
        )
        assert result["approved"] is True
        assert result["allocated_capital"] > 0

    def test_rejects_hold_signal(self):
        from backend.app.agents.risk_manager import RiskManager
        result = RiskManager(saldo_livre=1000.0).evaluate_trade(
            {"signal": "HOLD", "last_price": 50000.0}, ticker="BTC-USD", open_tickers=[]
        )
        assert result["approved"] is False

    def test_rejects_trade_with_zero_capital(self):
        from backend.app.agents.risk_manager import RiskManager
        result = RiskManager(saldo_livre=0.0).evaluate_trade(
            {"signal": "BUY", "last_price": 50000.0}, ticker="BTC-USD", open_tickers=[]
        )
        assert result["approved"] is False

    def test_sell_sets_correct_stop_and_target(self):
        from backend.app.agents.risk_manager import RiskManager
        price = 3000.0
        result = RiskManager(saldo_livre=1000.0).evaluate_trade(
            {"signal": "SELL", "last_price": price}, ticker="ETH-USD", open_tickers=[]
        )
        if result["approved"]:
            assert result["target_price"] < price
            assert result["stop_loss"] > price

    def test_buy_sets_correct_stop_and_target(self):
        from backend.app.agents.risk_manager import RiskManager
        price = 50000.0
        result = RiskManager(saldo_livre=1000.0).evaluate_trade(
            {"signal": "BUY", "last_price": price}, ticker="BTC-USD", open_tickers=[]
        )
        if result["approved"]:
            assert result["target_price"] > price
            assert result["stop_loss"] < price

    def test_blocks_correlated_asset_when_btc_open(self):
        from backend.app.agents.risk_manager import RiskManager
        result = RiskManager(saldo_livre=1000.0).evaluate_trade(
            {"signal": "BUY", "last_price": 3000.0},
            ticker="ETH-USD", open_tickers=["BTC-USD"]
        )
        assert result["approved"] is False
        assert "correla" in result["reason"].lower()

    def test_allows_uncorrelated_asset_when_btc_open(self):
        from backend.app.agents.risk_manager import RiskManager
        result = RiskManager(saldo_livre=1000.0).evaluate_trade(
            {
                "signal": "BUY", 
                "last_price": 150.0,
                "target_price": 160.0,
                "stop_loss": 140.0,
                "confidence": 70
            },
            ticker="SOL-USD", open_tickers=["BTC-USD"]
        )
        assert result["approved"] is True

    def test_allows_eth_when_no_open_positions(self):
        from backend.app.agents.risk_manager import RiskManager
        result = RiskManager(saldo_livre=1000.0).evaluate_trade(
            {
                "signal": "BUY", 
                "last_price": 3000.0,
                "target_price": 3200.0,
                "stop_loss": 2800.0,
                "confidence": 70
            },
            ticker="ETH-USD", open_tickers=[]
        )
        assert result["approved"] is True


# ============================================================================
# EXECUTOR AGENT TESTS
# ============================================================================

class TestExecutorAgent:

    def test_execute_order_inserts_trade(self):
        import tempfile
        import os
        from backend.app.agents.executor import ExecutorAgent

        # Usar arquivo temporário pois execute_order fecha a conexão internamente
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            # Inicializar schema no arquivo temporário com o sqlite3 REAL
            _real_connect = sqlite3.connect
            conn_setup = _real_connect(db_path)
            conn_setup.execute("""
                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT, side TEXT, shares REAL, entry_price REAL,
                    exit_price REAL, target_price REAL, stop_loss REAL,
                    entry_date TIMESTAMP, exit_date TIMESTAMP,
                    pnl_pct REAL, exit_reason TEXT, ai_rationale TEXT, status TEXT
                )
            """)
            conn_setup.execute("""
                CREATE TABLE portfolio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patrimonio_total REAL DEFAULT 0.0,
                    saldo_disponivel REAL DEFAULT 100.0,
                    em_posicoes REAL DEFAULT 0.0,
                    updated_at TIMESTAMP
                )
            """)
            conn_setup.execute(
                "INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, updated_at) VALUES (0.0, 100.0, 0.0, ?)",
                (datetime.now(),)
            )
            conn_setup.commit()
            conn_setup.close()

            # Patch que usa a referência REAL ao sqlite3.connect (evita recursão)
            with patch("backend.app.agents.executor.sqlite3.connect",
                       side_effect=lambda p, **kwargs: _real_connect(db_path)):
                executor = ExecutorAgent()
                result = executor.execute_order(
                    ticker="BTC-USD",
                    decision={"approved": True, "allocated_capital": 10.0,
                              "target_price": 65000.0, "stop_loss": 60000.0},
                    analysis={"signal": "BUY", "last_price": 62000.0, "reason": "Test"}
                )

            assert result["status"] == "executed"
            assert result["shares"] > 0

            # Re-abrir com a referência real para verificar a persistência
            conn_check = _real_connect(db_path)
            row = conn_check.execute(
                "SELECT status FROM trades WHERE ticker='BTC-USD'"
            ).fetchone()
            conn_check.close()
            assert row is not None and row[0] == "active"

        finally:
            os.unlink(db_path)

    def test_execute_order_rejected_when_not_approved(self):
        from backend.app.agents.executor import ExecutorAgent
        conn = _init_in_memory_db()
        with patch("backend.app.agents.executor.sqlite3.connect", return_value=conn):
            result = ExecutorAgent().execute_order(
                ticker="BTC-USD",
                decision={"approved": False, "reason": "Veto"},
                analysis={"signal": "BUY", "last_price": 62000.0, "reason": ""}
            )
        assert result["status"] == "rejected"
        count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert count == 0

    def test_close_order_positive_pnl_on_profit(self):
        from backend.app.agents.executor import ExecutorAgent
        conn = _init_in_memory_db()
        conn.execute(
            "INSERT INTO trades (ticker, side, shares, entry_price, target_price, "
            "stop_loss, entry_date, ai_rationale, status) VALUES (?,?,?,?,?,?,?,?,?)",
            ("BTC-USD", "BUY", 0.001, 60000.0, 65000.0, 58000.0, datetime.now(), "t", "active")
        )
        conn.commit()
        trade_id = conn.execute("SELECT MAX(id) FROM trades").fetchone()[0]
        with patch("backend.app.agents.executor.sqlite3.connect", return_value=conn):
            result = ExecutorAgent().close_order(trade_id, 65000.0, "Take Profit hit")
        assert result["status"] == "closed"
        assert result["pnl_pct"] > 0

    def test_close_order_negative_pnl_on_loss(self):
        from backend.app.agents.executor import ExecutorAgent
        conn = _init_in_memory_db()
        conn.execute(
            "INSERT INTO trades (ticker, side, shares, entry_price, target_price, "
            "stop_loss, entry_date, ai_rationale, status) VALUES (?,?,?,?,?,?,?,?,?)",
            ("ETH-USD", "BUY", 0.01, 3000.0, 3200.0, 2940.0, datetime.now(), "t", "active")
        )
        conn.commit()
        trade_id = conn.execute("SELECT MAX(id) FROM trades").fetchone()[0]
        with patch("backend.app.agents.executor.sqlite3.connect", return_value=conn):
            result = ExecutorAgent().close_order(trade_id, 2940.0, "Stop Loss hit")
        assert result["status"] == "closed"
        assert result["pnl_pct"] < 0

    def test_close_order_returns_error_for_invalid_id(self):
        from backend.app.agents.executor import ExecutorAgent
        conn = _init_in_memory_db()
        with patch("backend.app.agents.executor.sqlite3.connect", return_value=conn):
            result = ExecutorAgent().close_order(9999, 50000.0, "Test")
        assert result["status"] == "error"


# ============================================================================
# FEED TESTS (retry & fallback)
# ============================================================================

class TestFeed:

    def test_fetch_returns_dataframe_on_success(self):
        from backend.app.data.feed import fetch_recent_data
        mock_df = pd.DataFrame({
            "Close": [100.0, 101.0], "Open": [99.0, 100.0],
            "High": [102.0, 103.0], "Low": [98.0, 99.0], "Volume": [1000, 2000],
        }, index=pd.date_range("2024-01-01", periods=2, freq="15min"))
        mock_df.index.name = "Datetime"
        with patch("backend.app.data.feed.yf.download", return_value=mock_df):
            result = fetch_recent_data("BTC-USD")
        assert result is not None
        assert "close" in result.columns

    def test_fetch_retries_on_transient_error(self):
        from backend.app.data.feed import fetch_recent_data
        call_count = 0

        def flaky_download(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Timeout simulado")
            df = pd.DataFrame(
                {"Close": [100.0], "Open": [99.0], "High": [101.0],
                 "Low": [98.0], "Volume": [1000]},
                index=pd.date_range("2024-01-01", periods=1, freq="15min")
            )
            df.index.name = "Datetime"
            return df

        with patch("backend.app.data.feed.yf.download", side_effect=flaky_download), \
             patch("backend.app.data.feed.time.sleep"):
            result = fetch_recent_data("BTC-USD", max_retries=3)
        assert call_count == 3
        assert result is not None

    def test_fetch_returns_none_after_all_retries_fail(self):
        from backend.app.data.feed import fetch_recent_data
        with patch("backend.app.data.feed.yf.download",
                   side_effect=ConnectionError("Timeout")), \
             patch("backend.app.data.feed.time.sleep"):
            result = fetch_recent_data("BTC-USD", max_retries=3)
        assert result is None
