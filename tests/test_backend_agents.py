"""
Tests for the Backend AI Committee Agents
==========================================
Covers: MarketAnalyst (Gemini LLM), RiskManager (Kelly + Correlation), ExecutorAgent (open/close).
Uses AsyncMock to avoid real HTTP calls and in-memory SQLite for DB operations.
"""
import ast
import inspect
import sqlite3
import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from unittest.mock import patch

def _daily_breakout_df(n=260, breakout=1.02) -> pd.DataFrame:
    """DataFrame DIÁRIO (schema do feed: date/open/high/low/close/volume)
    com >=201 barras e um breakout Donchian VÁLIDO na última barra:
    tendência de alta (preço > SMA-200), rompe a máxima de 20 dias, volume
    2,5x, RSI ~68 (dentro do teto 75). breakout=1.0 -> a última barra NÃO
    rompe (caso negativo, deve dar HOLD).

    A série usa default_rng(0) (PCG64, determinístico e estável entre
    versões do numpy) — o fixture foi verificado contra o compute_signal
    REAL: gera Candidate com breakout=1.02, None com breakout=1.0.
    """
    rng = np.random.default_rng(0)
    price = 85.0
    closes = []
    for _ in range(n - 1):
        price += 0.015 + rng.normal(0, 0.35)
        closes.append(price)
    recent_high = max(closes[-20:])
    closes.append(recent_high * breakout)
    highs = [c * 1.006 if i < n - 1 else c * 1.001 for i, c in enumerate(closes)]
    return pd.DataFrame({'date': pd.date_range('2023-01-02', periods=n, freq='D'), 'close': closes, 'open': [c * 0.999 for c in closes], 'high': highs, 'low': [c * 0.994 for c in closes], 'volume': [1000] * (n - 1) + [2500]})

def _init_in_memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(':memory:')
    conn.execute('\n        CREATE TABLE trades (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            ticker TEXT, side TEXT, shares REAL, entry_price REAL,\n            exit_price REAL, target_price REAL, stop_loss REAL,\n            entry_date TIMESTAMP, exit_date TIMESTAMP,\n            pnl_pct REAL, exit_reason TEXT, ai_rationale TEXT, status TEXT, signal_id TEXT)\n    ')
    conn.execute('\n        CREATE TABLE portfolio (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            patrimonio_total REAL DEFAULT 0.0,\n            saldo_disponivel REAL DEFAULT 100.0,\n            em_posicoes REAL DEFAULT 0.0,\n            margem_operavel REAL,\n            updated_at TIMESTAMP\n        )\n    ')
    conn.execute('INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, updated_at) VALUES (0.0, 100.0, 0.0, ?)', (datetime.now(),))
    conn.commit()
    return conn

class TestMarketAnalyst:
    """Fase 1 Commit 2: sinal DETERMINÍSTICO Donchian, sem LLM. Ticker B3
    (PETR4.SA) porque resolve_market só reconhece B3. IBOV mockado para não
    bloquear (get_ibov_data -> None => ibov_in_uptrend => True), isolando o
    teste do sinal do filtro macro."""

    @pytest.mark.asyncio
    async def test_hold_no_rompimento_sem_aprovacao_dos_dados(self):
        from backend.app.agents.market_analyst import MarketAnalyst
        with patch('backend.app.data.feed.fetch_recent_data', return_value=_daily_breakout_df(breakout=1.02)), patch('backend.app.agents.market_analyst.get_ibov_data', return_value=None):
            result = await MarketAnalyst('PETR4.SA').analyze()
        assert result['signal'] == 'HOLD'
        assert result['last_price'] > 0

    @pytest.mark.asyncio
    async def test_hold_sem_rompimento(self):
        from backend.app.agents.market_analyst import MarketAnalyst
        with patch('backend.app.data.feed.fetch_recent_data', return_value=_daily_breakout_df(breakout=1.0)), patch('backend.app.agents.market_analyst.get_ibov_data', return_value=None):
            result = await MarketAnalyst('PETR4.SA').analyze()
        assert result['signal'] == 'HOLD'

    @pytest.mark.asyncio
    async def test_hold_quando_ibov_abaixo_da_sma50(self):
        from backend.app.agents.market_analyst import MarketAnalyst
        with patch('backend.app.data.feed.fetch_recent_data', return_value=_daily_breakout_df(breakout=1.02)), patch('backend.app.agents.market_analyst.ibov_in_uptrend', return_value=False):
            result = await MarketAnalyst('PETR4.SA').analyze()
        assert result['signal'] == 'HOLD'
        assert 'IBOV' in result['reason']

    @pytest.mark.asyncio
    async def test_hold_com_poucas_barras_diarias(self):
        from backend.app.agents.market_analyst import MarketAnalyst
        with patch('backend.app.data.feed.fetch_recent_data', return_value=_daily_breakout_df(n=150)):
            result = await MarketAnalyst('PETR4.SA').analyze()
        assert result['signal'] == 'HOLD'
        assert 'insuficientes' in result['reason'].lower()

    @pytest.mark.asyncio
    async def test_hold_sem_dado(self):
        from backend.app.agents.market_analyst import MarketAnalyst
        with patch('backend.app.data.feed.fetch_recent_data', return_value=None):
            result = await MarketAnalyst('PETR4.SA').analyze()
        assert result['signal'] == 'HOLD'

    @pytest.mark.asyncio
    async def test_nunca_gera_sell_long_only(self):
        from backend.app.agents.market_analyst import MarketAnalyst
        with patch('backend.app.data.feed.fetch_recent_data', return_value=_daily_breakout_df(breakout=1.02)), patch('backend.app.agents.market_analyst.get_ibov_data', return_value=None):
            result = await MarketAnalyst('PETR4.SA').analyze()
        assert result['signal'] in ('BUY', 'HOLD')

    def test_llm_saiu_do_caminho_de_decisao(self):
        """Prova estrutural (AST): o módulo de decisão de entrada não importa
        ResilientLLMClient nem chama generate_text. É o núcleo do Commit 2 —
        o LLM não é mais gatilho de trade."""
        import backend.app.agents.market_analyst as ma
        tree = ast.parse(inspect.getsource(ma))
        importados, nomes = (set(), set())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    importados.add(alias.name)
            if isinstance(node, ast.Attribute):
                nomes.add(node.attr)
            if isinstance(node, ast.Name):
                nomes.add(node.id)
        assert 'ResilientLLMClient' not in importados
        assert 'ResilientLLMClient' not in nomes
        assert 'generate_text' not in nomes
        assert 'generate_text_async' not in nomes

class TestSizingAlinhadoComBacktest:
    """Prova que o dimensionamento do fluxo AO VIVO (RiskManager) é
    IDÊNTICO ao do backtest: a mesma função
    trading_bot.risk.position_sizing.calculate_position_size, com os mesmos
    inputs de capital. Rodar ao vivo exatamente o que foi validado, sizing
    incluído."""

    @pytest.fixture(autouse=True)
    def _breaker_liberado(self):
        with patch('trading_bot.risk.circuit_breaker.CircuitBreaker.can_trade', return_value=True):
            yield

    def test_alocacao_ao_vivo_bate_com_calculate_position_size(self, unit_approval_identity):
        from backend.app.agents.risk_manager import RiskManager
        from backend.app.runtime_config import RuntimeConfig
        from trading_bot.risk.position_sizing import calculate_position_size
        cfg = RuntimeConfig.load()
        capital_cash, em_posicoes = (300.0, 100.0)
        open_tickers = ['MGLU3.SA']
        ref_eq = capital_cash + em_posicoes
        signal = {'signal': 'BUY', 'current_price': 10.0, 'target_price': 12.0, 'stop_loss': 9.0, 'confidence': 80, **unit_approval_identity('PETR4.SA'), 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc), 'reason': 'Test reason'}
        rm = RiskManager(saldo_livre=capital_cash, em_posicoes=em_posicoes, reference_equity=ref_eq)
        decision = rm.evaluate_trade(signal, ticker='PETR4.SA', open_tickers=open_tickers)
        esperado = calculate_position_size(capital_cash=capital_cash, open_positions_capital=em_posicoes, kelly_fraction=cfg.kelly_fraction, max_positions=cfg.max_positions, current_open_count=len(open_tickers), max_position_fraction=cfg.max_position_fraction, reference_equity=ref_eq)
        assert decision['approved'] is True
        assert decision['allocated_capital'] == pytest.approx(esperado)

    def test_sizing_ignora_confianca(self, unit_approval_identity):
        """Confiança diferente NÃO muda a alocação (Kelly agora é fixo, não
        derivado de confiança como antes)."""
        from backend.app.agents.risk_manager import RiskManager
        base = {'signal': 'BUY', 'current_price': 10.0, 'target_price': 12.0, 'stop_loss': 9.0, **unit_approval_identity('PETR4.SA'), 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc), 'reason': 'Test reason', 'confidence': 70}
        rm = RiskManager(saldo_livre=300.0, em_posicoes=0.0, reference_equity=300.0)
        a = rm.evaluate_trade({**base, 'confidence': 20}, ticker='PETR4.SA', open_tickers=[])
        b = rm.evaluate_trade({**base, 'confidence': 95}, ticker='PETR4.SA', open_tickers=[])
        assert a['approved'] and b['approved']
        assert a['allocated_capital'] == pytest.approx(b['allocated_capital'])

class TestRiskManager:

    @pytest.fixture(autouse=True)
    def _breaker_liberado(self):
        with patch('trading_bot.risk.circuit_breaker.CircuitBreaker.can_trade', return_value=True):
            yield

    def test_rejeita_quando_circuit_breaker_ativo(self, unit_approval_identity):
        from backend.app.agents.risk_manager import RiskManager
        with patch('trading_bot.risk.circuit_breaker.CircuitBreaker.can_trade', return_value=False):
            result = RiskManager(saldo_livre=1000.0).evaluate_trade({'signal': 'BUY', 'current_price': 50000.0, 'target_price': 55000.0, 'stop_loss': 48000.0, 'confidence': 70, **unit_approval_identity('BTC-USD'), 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc), 'reason': 'Test reason'}, ticker='BTC-USD', open_tickers=[])
        assert result['approved'] is False
        assert 'Circuit Breaker' in result['reason']

    def test_rejeita_fail_closed_quando_breaker_lanca_excecao(self, unit_approval_identity):
        from backend.app.agents.risk_manager import RiskManager
        with patch('trading_bot.risk.circuit_breaker.CircuitBreaker.can_trade', side_effect=RuntimeError('db indisponível')):
            result = RiskManager(saldo_livre=1000.0).evaluate_trade({'signal': 'BUY', 'current_price': 50000.0, 'target_price': 55000.0, 'stop_loss': 48000.0, 'confidence': 70, **unit_approval_identity('BTC-USD'), 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc), 'reason': 'Test reason'}, ticker='BTC-USD', open_tickers=[])
        assert result['approved'] is False
        assert 'fail-closed' in result['reason']

    def test_approves_trade_with_sufficient_capital(self, unit_approval_identity):
        from backend.app.agents.risk_manager import RiskManager
        result = RiskManager(saldo_livre=1000.0, reference_equity=1000.0).evaluate_trade({'signal': 'BUY', 'current_price': 50000.0, 'target_price': 55000.0, 'stop_loss': 48000.0, 'confidence': 70, **unit_approval_identity('BTC-USD'), 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc), 'reason': 'Test reason'}, ticker='BTC-USD', open_tickers=[])
        assert result['approved'] is True
        assert result['allocated_capital'] > 0

    def test_rejects_hold_signal(self, unit_approval_identity):
        from backend.app.agents.risk_manager import RiskManager
        result = RiskManager(saldo_livre=1000.0, reference_equity=1000.0).evaluate_trade({'signal': 'HOLD', 'current_price': 50000.0, **unit_approval_identity('BTC-USD'), 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc), 'reason': 'Test reason', 'target_price': 999999.0, 'stop_loss': 1.0, 'confidence': 70}, ticker='BTC-USD', open_tickers=[])
        assert result['approved'] is False

    def test_rejects_trade_with_zero_capital(self, unit_approval_identity):
        from backend.app.agents.risk_manager import RiskManager
        result = RiskManager(saldo_livre=0.0, reference_equity=1000.0).evaluate_trade({'signal': 'BUY', 'current_price': 50000.0, **unit_approval_identity('BTC-USD'), 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc), 'reason': 'Test reason', 'target_price': 999999.0, 'stop_loss': 1.0, 'confidence': 70}, ticker='BTC-USD', open_tickers=[])
        assert result['approved'] is False

    def test_sell_sets_correct_stop_and_target(self, unit_approval_identity):
        from backend.app.agents.risk_manager import RiskManager
        price = 3000.0
        result = RiskManager(saldo_livre=1000.0, reference_equity=1000.0).evaluate_trade({'signal': 'SELL', 'current_price': price, **unit_approval_identity('ETH-USD'), 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc), 'reason': 'Test reason', 'target_price': 2800.0, 'stop_loss': 3200.0, 'confidence': 70}, ticker='ETH-USD', open_tickers=[])
        assert result['approved'] is True
        assert result['target_price'] < price
        assert result['stop_loss'] > price

    def test_buy_sets_correct_stop_and_target(self, unit_approval_identity):
        from backend.app.agents.risk_manager import RiskManager
        price = 50000.0
        result = RiskManager(saldo_livre=1000.0, reference_equity=1000.0).evaluate_trade({'signal': 'BUY', 'current_price': price, **unit_approval_identity('BTC-USD'), 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc), 'reason': 'Test reason', 'target_price': 999999.0, 'stop_loss': 1.0, 'confidence': 70}, ticker='BTC-USD', open_tickers=[])
        assert result['approved'] is True
        assert result['target_price'] > price
        assert result['stop_loss'] < price

    def test_blocks_correlated_asset_when_btc_open(self, unit_approval_identity):
        from backend.app.agents.risk_manager import RiskManager
        result = RiskManager(saldo_livre=1000.0, reference_equity=1000.0).evaluate_trade({'signal': 'BUY', 'current_price': 3000.0, **unit_approval_identity('ETH-USD'), 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc), 'reason': 'Test reason', 'target_price': 999999.0, 'stop_loss': 1.0, 'confidence': 70}, ticker='ETH-USD', open_tickers=['BTC-USD'])
        assert result['approved'] is False
        assert 'correla' in result['reason'].lower()

    def test_allows_uncorrelated_asset_when_btc_open(self, unit_approval_identity):
        from backend.app.agents.risk_manager import RiskManager
        result = RiskManager(saldo_livre=1000.0, reference_equity=1000.0).evaluate_trade({'signal': 'BUY', 'current_price': 150.0, 'target_price': 160.0, 'stop_loss': 140.0, 'confidence': 70, **unit_approval_identity('SOL-USD'), 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc), 'reason': 'Test reason'}, ticker='SOL-USD', open_tickers=['BTC-USD'])
        assert result['approved'] is True

    def test_allows_eth_when_no_open_positions(self, unit_approval_identity):
        from backend.app.agents.risk_manager import RiskManager
        result = RiskManager(saldo_livre=1000.0, reference_equity=1000.0).evaluate_trade({'signal': 'BUY', 'current_price': 3000.0, 'target_price': 3200.0, 'stop_loss': 2800.0, 'confidence': 70, **unit_approval_identity('ETH-USD'), 'dataset_approved': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc), 'reason': 'Test reason'}, ticker='ETH-USD', open_tickers=[])
        assert result['approved'] is True

class TestExecutorAgent:

    def test_execute_order_inserts_trade(self, unit_approval_identity):
        import tempfile
        import os
        from backend.app.agents.executor import ExecutorAgent
        from backend.app.agents.contracts import ApprovedExecutionIntent, TypedSignal, RiskDecision
        from datetime import datetime, timezone

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            _real_connect = sqlite3.connect
            conn_setup = _real_connect(db_path)
            conn_setup.execute('\n                CREATE TABLE trades (\n                    id INTEGER PRIMARY KEY AUTOINCREMENT,\n                    ticker TEXT, side TEXT, shares REAL, entry_price REAL,\n                    exit_price REAL, target_price REAL, stop_loss REAL,\n                    entry_date TIMESTAMP, exit_date TIMESTAMP,\n                    pnl_pct REAL, exit_reason TEXT, ai_rationale TEXT, status TEXT, signal_id TEXT)\n            ')
            conn_setup.execute('\n                CREATE TABLE portfolio (\n                    id INTEGER PRIMARY KEY AUTOINCREMENT,\n                    patrimonio_total REAL DEFAULT 0.0,\n                    saldo_disponivel REAL DEFAULT 100.0,\n                    em_posicoes REAL DEFAULT 0.0,\n                    margem_operavel REAL,\n                    updated_at TIMESTAMP\n                )\n            ')
            conn_setup.execute('INSERT INTO portfolio (patrimonio_total, saldo_disponivel, em_posicoes, updated_at) VALUES (0.0, 100.0, 0.0, ?)', (datetime.now(),))
            conn_setup.commit()
            conn_setup.close()

            sig = TypedSignal(
                **unit_approval_identity("BTC-USD"),
                side="BUY",
                price=62000.0,
                target_price=65000.0,
                stop_loss=60000.0,
                reason="Test signal",
                dataset_approved=True,
                generated_at=datetime.now(timezone.utc),
            )
            dec = RiskDecision(
                signal_id=sig.signal_id,
                approved=True,
                allocated_capital=10.0,
                target_price=65000.0,
                stop_loss=60000.0,
                reason="Test reason",
                decision_timestamp=datetime.now(timezone.utc),
            )
            from tests.conftest import make_test_evidenced_quote
            intent = ApprovedExecutionIntent(
                signal=sig,
                risk_decision=dec,
                execution_quote=make_test_evidenced_quote("BTC-USD", 62000.0),
            )

            with patch('backend.app.agents.executor.sqlite3.connect', side_effect=lambda p, **kwargs: _real_connect(db_path)):
                executor = ExecutorAgent(db_path=db_path)
                result = executor.execute_order(intent)
            assert result['status'] == 'executed'
            assert result['shares'] > 0
            conn_check = _real_connect(db_path)
            row = conn_check.execute("SELECT status FROM trades WHERE ticker='BTC-USD'").fetchone()
            conn_check.close()
            assert row is not None and row[0] == 'active'
        finally:
            os.unlink(db_path)

    def test_execute_order_rejected_when_not_approved(self):
        from backend.app.agents.executor import ExecutorAgent
        conn = _init_in_memory_db()
        with patch('backend.app.agents.executor.sqlite3.connect', return_value=conn):
            # Raw unapproved dictionary rejected before transaction
            result = ExecutorAgent().execute_order({'approved': False, 'reason': 'Veto'})
        assert result['status'] == 'rejected'
        count = conn.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
        assert count == 0

    def test_close_order_positive_pnl_on_profit(self):
        from backend.app.agents.executor import ExecutorAgent
        from tests.conftest import make_test_evidenced_quote
        conn = _init_in_memory_db()
        conn.execute('UPDATE portfolio SET em_posicoes = 60.0 WHERE id = 1')
        conn.execute('INSERT INTO trades (ticker, side, shares, entry_price, target_price, stop_loss, entry_date, ai_rationale, status) VALUES (?,?,?,?,?,?,?,?,?)', ('BTC-USD', 'BUY', 0.001, 60000.0, 65000.0, 58000.0, datetime.now(), 't', 'active'))
        conn.commit()
        trade_id = conn.execute('SELECT MAX(id) FROM trades').fetchone()[0]
        ev = make_test_evidenced_quote('BTC-USD', 65000.0)
        with patch('backend.app.agents.executor.sqlite3.connect', return_value=conn):
            result = ExecutorAgent().close_order(trade_id, 65000.0, 'Take Profit hit', evidence=ev)
        assert result['status'] == 'closed'
        assert result['pnl_pct'] > 0

    def test_close_order_negative_pnl_on_loss(self):
        from backend.app.agents.executor import ExecutorAgent
        from tests.conftest import make_test_evidenced_quote
        conn = _init_in_memory_db()
        conn.execute('UPDATE portfolio SET em_posicoes = 30.0 WHERE id = 1')
        conn.execute('INSERT INTO trades (ticker, side, shares, entry_price, target_price, stop_loss, entry_date, ai_rationale, status) VALUES (?,?,?,?,?,?,?,?,?)', ('ETH-USD', 'BUY', 0.01, 3000.0, 3200.0, 2940.0, datetime.now(), 't', 'active'))
        conn.commit()
        trade_id = conn.execute('SELECT MAX(id) FROM trades').fetchone()[0]
        ev = make_test_evidenced_quote('ETH-USD', 2940.0)
        with patch('backend.app.agents.executor.sqlite3.connect', return_value=conn):
            result = ExecutorAgent().close_order(trade_id, 2940.0, 'Stop Loss hit', evidence=ev)
        assert result['status'] == 'closed'
        assert result['pnl_pct'] < 0

    def test_close_order_returns_error_for_invalid_id(self):
        from backend.app.agents.executor import ExecutorAgent
        from tests.conftest import make_test_evidenced_quote
        conn = _init_in_memory_db()
        ev = make_test_evidenced_quote('PETR4.SA', 50000.0)
        with patch('backend.app.agents.executor.sqlite3.connect', return_value=conn):
            result = ExecutorAgent().close_order(9999, 50000.0, 'Test', evidence=ev)
        assert result['status'] == 'error'

class TestFeed:

    def test_fetch_returns_dataframe_on_success(self):
        from backend.app.data.feed import fetch_recent_data
        mock_df = pd.DataFrame({'Close': [100.0, 101.0], 'Open': [99.0, 100.0], 'High': [102.0, 103.0], 'Low': [98.0, 99.0], 'Volume': [1000, 2000]}, index=pd.date_range('2024-01-01', periods=2, freq='15min'))
        mock_df.index.name = 'Datetime'
        with patch('backend.app.data.feed.yf.download', return_value=mock_df):
            result = fetch_recent_data('BTC-USD')
        assert result is not None
        assert 'close' in result.columns

    def test_fetch_retries_on_transient_error(self):
        from backend.app.data.feed import fetch_recent_data
        call_count = 0

        def flaky_download(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError('Timeout simulado')
            df = pd.DataFrame({'Close': [100.0], 'Open': [99.0], 'High': [101.0], 'Low': [98.0], 'Volume': [1000]}, index=pd.date_range('2024-01-01', periods=1, freq='15min'))
            df.index.name = 'Datetime'
            return df
        with patch('backend.app.data.feed.yf.download', side_effect=flaky_download), patch('backend.app.data.feed.time.sleep'):
            result = fetch_recent_data('BTC-USD', max_retries=3)
        assert call_count == 3
        assert result is not None

    def test_fetch_returns_none_after_all_retries_fail(self):
        from backend.app.data.feed import fetch_recent_data
        with patch('backend.app.data.feed.yf.download', side_effect=ConnectionError('Timeout')), patch('backend.app.data.feed.time.sleep'):
            result = fetch_recent_data('BTC-USD', max_retries=3)
        assert result is None
