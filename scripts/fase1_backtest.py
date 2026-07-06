#!/usr/bin/env python3
"""
Fase 1 — Backtest do Motor de Sinais
Lê configurações do settings.yaml e executa o backtest completo nos 3 regimes.
"""
import sys
import logging
import argparse
from datetime import date
import yaml

sys.path.insert(0, ".")

from trading_bot.data.ingestion import fetch_universe_yfinance
from trading_bot.backtest.engine import run_full_backtest
from trading_bot.backtest.metrics import compute_aggregate_metrics
from trading_bot.core.config import AppConfig, setup_logging

def main():
    parser = argparse.ArgumentParser(description="Executa o backtest (Fase 1)")
    parser.parse_args()

    print("Carregando configurações...")
    cfg = AppConfig.load()
    setup_logging(cfg)
    
    tickers = cfg.get("_universe", default=[])
    sig_cfg = cfg.get("signals", default={})
    risk_cfg = cfg.get("risk", default={})
    bt_cfg = cfg.get("backtest", default={})

    print(f"Buscando dados para {len(tickers)} ativos...")
    # Fetch from 1 year before the first regime to ensure SMA-200 and IBOV filter have data
    start_date = date(2019, 1, 1)
    data = fetch_universe_yfinance(tickers, start=start_date)

    print(f"\nRodando Backtest - Estratégia: {sig_cfg.get('strategy', 'default')}")
    print(f"Capital: R${risk_cfg.get('capital_initial', 300.0):.2f}")
    
    # Monta os parâmetros do sinal lidos do settings.yaml
    signal_params = {
        "breakout_period": sig_cfg.get("breakout_period", 20),
        "volume_mult": sig_cfg.get("volume_multiplier", 2.0),
        "sma_trend_period": sig_cfg.get("sma_trend_period", 200),
        "rsi_max": sig_cfg.get("rsi_max", 75.0),
        "stop_pct": sig_cfg.get("stop_pct", 0.04),
        "target_pct": sig_cfg.get("target_pct", 0.10)
    }

    results = run_full_backtest(
        data=data,
        capital=risk_cfg.get("capital_initial", 300.0),
        kelly_fraction=risk_cfg.get("kelly_fraction", 0.25),
        max_positions=risk_cfg.get("max_positions", 3),
        max_hold_days=sig_cfg.get("max_hold_days", 15),
        signal_params=signal_params,
        regimes=bt_cfg.get("regimes"),
        ibov_filter=sig_cfg.get("ibov_filter", True),
        brokerage_pct=risk_cfg.get("brokerage_pct", 0.0003),
        spread_pct=risk_cfg.get("spread_est_pct", 0.0002)
    )

    agg = compute_aggregate_metrics(
        results,
        min_sharpe_per_regime=bt_cfg.get("min_sharpe_per_regime", 0.5),
        min_sharpe_aggregate=bt_cfg.get("min_sharpe_aggregate", 1.0)
    )
    
    print("\n" + "="*50)
    print("RESULTADO AGREGADO")
    print("="*50)
    print(f"Trades totais: {sum(r.n_trades for r in results)}")
    gate_status = "✅ PASSA" if agg.overall_pass else "❌ REPROVA"
    print(f"Sharpe Agregado: {agg.sharpe_aggregate:.2f} ({gate_status})")
    print("\nDetalhes por Regime:")
    for i, m in enumerate(agg.regimes):
        cl = results[i].closed_trades
        w = [t for t in cl if t.pnl_pct > 0]
        wr = len(w) / len(cl) if cl else 0.0
        aw = sum(t.pnl_pct for t in w) / len(w) * 100 if w else 0.0
        l2 = [t for t in cl if t.pnl_pct <= 0]
        al = sum(t.pnl_pct for t in l2) / len(l2) * 100 if l2 else 0.0
        print(f"  {m.regime[:18]:<18}: n={m.n_trades:<3} wr={wr:.0%}  aw={aw:+.1f}%  al={al:+.1f}%  Sh={m.sharpe:.2f}")

if __name__ == "__main__":
    main()
