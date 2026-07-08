#!/usr/bin/env python3
"""
Fase 2 — Orquestrador de Paper Trading
Roda a verificação diária, gera sinais, pede aprovação via Telegram e envia para a corretora (Mock).
"""
import sys
import logging
import argparse
from datetime import date

sys.path.insert(0, ".")

from trading_bot.data.ingestion import fetch_universe_yfinance
from trading_bot.signals.engine import scan_universe, get_ibov_data
from trading_bot.risk.circuit_breaker import CircuitBreaker
from trading_bot.risk.position_sizing import PositionSizing
from trading_bot.core.config import AppConfig, setup_logging
from trading_bot.core.telegram import TelegramNotifier
from trading_bot.broker.cedro import CedroBroker

def main():
    parser = argparse.ArgumentParser(description="Orquestrador Fase 2 (Paper Trading)")
    parser.parse_args()

    print("Carregando configurações...")
    cfg = AppConfig.load()
    setup_logging(cfg)
    logger = logging.getLogger("Fase2")
    
    tickers = cfg.get("_universe", "tickers", default=[])
    sig_cfg = cfg.get("signals", default={})
    risk_cfg = cfg.get("risk", default={})

    # Inicializa Módulos de Execução
    telegram_token = cfg.get("credentials", "telegram_bot_token", default="")
    telegram_chat = cfg.get("credentials", "telegram_chat_id", default="")
    notifier = TelegramNotifier(bot_token=telegram_token, chat_id=telegram_chat)
    broker = CedroBroker() # Instancia mock SQLite

    print(f"Buscando dados para {len(tickers)} ativos...")
    start_date = date(2023, 1, 1)
    data = fetch_universe_yfinance(tickers, start=start_date)
    ibov = get_ibov_data(start_date)

    print("\nAnalisando sinais para hoje...")
    signal_params = {
        "breakout_period": sig_cfg.get("breakout_period", 20),
        "volume_mult": sig_cfg.get("volume_multiplier", 2.0),
        "sma_trend_period": sig_cfg.get("sma_trend_period", 200),
        "rsi_max": sig_cfg.get("rsi_max", 75.0),
        "stop_pct": sig_cfg.get("stop_pct", 0.04),
        "target_pct": sig_cfg.get("target_pct", 0.10)
    }

    hoje = date.today()
    candidates = scan_universe(data, ibov_df=ibov, ref_date=hoje, **signal_params)
    
    if not candidates:
        print("Nenhum sinal gerado hoje.")
        return

    # Inicia filtros de Risco
    cb = CircuitBreaker(cfg)
    if not cb.can_trade(hoje):
        print("⚠️ Circuit Breaker Ativado. Trading suspenso.")
        return

    capital = risk_cfg.get("capital_initial", 300.0) # Simulado
    ps = PositionSizing(cfg, capital=capital)
    
    print(f"\n{len(candidates)} candidatos encontrados. Aplicando filtro Kelly e Solicitando Aprovação...")
    
    for cand in candidates:
        # Filtro de risco (Kelly)
        qty = ps.calculate_quantity(cand.entry_price, cand.stop)
        if qty <= 0:
            logger.info("[%s] Rejeitado pelo Position Sizing (Qty 0)", cand.ticker)
            continue
            
        # Formata mensagem para Telegram
        msg = (
            f"🚨 <b>NOVO SINAL (PAPER TRADING)</b> 🚨\n\n"
            f"📈 Ativo: <b>{cand.ticker}</b>\n"
            f"💵 Entrada: R$ {cand.entry_price:.2f}\n"
            f"🛑 Stop Loss: R$ {cand.stop:.2f}\n"
            f"🎯 Target: R$ {cand.target:.2f}\n"
            f"📦 Qtd Recomendada: {qty} ações\n\n"
            f"RSI: {cand.rsi:.1f} | Vol: {cand.volume_ratio}x\n"
            f"Escolha uma ação abaixo para confirmar ou rejeitar:"
        )
        
        print(f"Enviando solicitação de aprovação para {cand.ticker} via Telegram...")
        # Aguarda resposta por 10 min
        is_approved = notifier.ask_for_approval(text=msg, timeout_minutes=10)
        
        if is_approved:
            print(f"✅ Trade APROVADO! Enviando ordem simulada para {cand.ticker}...")
            order = broker.submit_order(
                ticker=cand.ticker,
                side="BUY",
                qty=qty,
                price=cand.entry_price,
                stop=cand.stop,
                target=cand.target
            )
            print(f"Ordem {order.id} registrada no SQLite com sucesso!")
        else:
            print(f"❌ Trade REJEITADO (ou timeout) para {cand.ticker}.")

if __name__ == "__main__":
    main()
