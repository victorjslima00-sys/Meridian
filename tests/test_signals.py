import pytest
import pandas as pd
import numpy as np
from trading_bot.signals.engine import _rsi, _sma, _volume_ratio

def test_rsi_normal():
    # Série simples alternando altos e baixos
    close = pd.Series([10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11])
    rsi = _rsi(close, period=14)
    # Deve estar perto de 50
    assert 45 < rsi.iloc[-1] < 55

def test_rsi_all_up_no_losses():
    # Ativo que só sobe (avg_loss = 0)
    close = pd.Series([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25])
    rsi = _rsi(close, period=14)
    # Deve lidar com a divisão por zero e retornar 100.0
    assert rsi.iloc[-1] == 100.0

def test_rsi_all_down_no_gains():
    # Ativo que só cai (avg_gain = 0)
    close = pd.Series([25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10])
    rsi = _rsi(close, period=14)
    # Deve retornar 0.0
    assert rsi.iloc[-1] == 0.0

def test_sma():
    close = pd.Series([10, 20, 30, 40, 50])
    sma = _sma(close, period=3)
    assert np.isnan(sma.iloc[0])
    assert np.isnan(sma.iloc[1])
    assert sma.iloc[2] == 20.0
    assert sma.iloc[-1] == 40.0

def test_volume_ratio():
    vol = pd.Series([100]*20 + [200]) # 20 dias de 100, hoje = 200
    ratio = _volume_ratio(vol, ma_period=20)
    assert ratio == 2.0
