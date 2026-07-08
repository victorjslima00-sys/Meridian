import pytest
from datetime import date
import pandas as pd
from trading_bot.backtest.engine import run_regime_backtest, BacktestResult
from trading_bot.signals.engine import Candidate

def mock_compute_signal(df, ticker, **kwargs):
    # Dia 1 (idx 0): Sem sinal
    if len(df) == 1:
        return None
    # Dia 2 (idx 1): Gera sinal no dia 1 usando dados de dia 1
    # df traz os dados passados (inclusive o ultimo fechamento)
    last_date = df["ts"].iloc[-1]
    
    if last_date == date(2023, 1, 1):
        # Sinal gerado no dia 1 com stop 95.0
        return Candidate(
            ticker=ticker,
            score=0.8,
            entry_price=100.0,
            stop=95.0,
            target=110.0,
            signal_ts=last_date,
            rsi=60.0,
            volume_ratio=2.5,
            near_support=False,
            signal_details={}
        )
    return None

def test_engine_gap_abort(monkeypatch):
    monkeypatch.setattr("trading_bot.backtest.engine.get_ibov_data", lambda x: pd.DataFrame([{"ts": date(2023, 1, 1), "c": 100000}]))
    monkeypatch.setattr("trading_bot.backtest.engine.ibov_in_uptrend", lambda df, ts: True)
    
    # Substituir len(df) >= 200 checks (se houver) no engine.py não precisamos pois não mockamos o compute_signal dentro de engine pra requerer isso,
    # A própria estratégia requer 200 barras, mas no mock nós forçamos. Mas o engine.py faz if len(df_hist) < 200: continue
    # Então temos que colocar 200 barras na entrada!
    
    data_rows = []
    d = date(2022, 1, 1)
    for i in range(199):
        data_rows.append({"ts": d, "o": 100, "h": 105, "l": 95, "c": 100, "v": 1000, "adj_close": 100})
        d = pd.Timestamp(d) + pd.Timedelta(days=1)
        d = d.date()
        
    # As 3 barras finais:
    data_rows.extend([
        {"ts": date(2023, 1, 1), "o": 100, "h": 105, "l": 95, "c": 100, "v": 1000, "adj_close": 100},
        {"ts": date(2023, 1, 2), "o": 94, "h": 96, "l": 90, "c": 95, "v": 1000, "adj_close": 95},
        {"ts": date(2023, 1, 3), "o": 95, "h": 100, "l": 95, "c": 100, "v": 1000, "adj_close": 100},
    ])
    
    data = {"A": pd.DataFrame(data_rows)}
    
    monkeypatch.setattr("trading_bot.backtest.engine.compute_signal", mock_compute_signal)
    
    res = run_regime_backtest(
        data=data,
        regime_name="teste",
        start=date(2023, 1, 1),
        end=date(2023, 1, 3),
        capital=1000.0,
        ibov_filter=False
    )
    
    # O gap abort descarta o trade, logo ele não deve estar em "trades" (pois nem foi aberto)
    assert res.n_trades == 0

def test_engine_max_positions(monkeypatch):
    monkeypatch.setattr("trading_bot.backtest.engine.get_ibov_data", lambda x: None)
    
    # Se eu mandar 5 ativos dando sinal no mesmo dia, só pode abrir max_positions
    def mock_signal_always(df, ticker, **kwargs):
        return Candidate(
            ticker=ticker,
            score=0.9,
            entry_price=100.0,
            stop=90.0,
            target=120.0,
            signal_ts=df["ts"].iloc[-1],
            rsi=60.0,
            volume_ratio=2.5,
            near_support=False,
            signal_details={}
        )
    monkeypatch.setattr("trading_bot.backtest.engine.compute_signal", mock_signal_always)
    
    data_rows = []
    d = date(2022, 1, 1)
    for i in range(200):
        data_rows.append({"ts": d, "o": 100, "h": 105, "l": 95, "c": 100, "v": 1000, "adj_close": 100})
        d = pd.Timestamp(d) + pd.Timedelta(days=1)
        d = d.date()
        
    data_rows.extend([
        {"ts": date(2023, 1, 1), "o": 100, "h": 105, "l": 95, "c": 100, "v": 1000, "adj_close": 100},
        {"ts": date(2023, 1, 2), "o": 100, "h": 105, "l": 95, "c": 100, "v": 1000, "adj_close": 100},
    ])
    df_base = pd.DataFrame(data_rows)
    
    data = {f"A{i}": df_base.copy() for i in range(5)}
    
    monkeypatch.setattr("trading_bot.backtest.engine.ibov_in_uptrend", lambda df, ts: True)
    res = run_regime_backtest(
        data=data,
        regime_name="teste_max",
        start=date(2023, 1, 1),
        end=date(2023, 1, 2),
        capital=1000.0,
        max_positions=2, # O limite
        ibov_filter=False
    )
    
    assert len(res.trades) == 2 # Only 2 trades should have been executed because of max_positions=2
