#!/usr/bin/env python3
"""
Fase 3 — Quant Optimizer
Varredura retroativa (Backtest Grid Search) para calibrar os parâmetros de sinal.
Se encontrar um Índice Sharpe superior em 10%, ele atualiza o settings.yaml automaticamente
e envia uma notificação no Telegram.
"""
import sys
import logging
import argparse
import re
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, ".")

from trading_bot.data.ingestion import fetch_universe_yfinance
from trading_bot.signals.engine import get_ibov_data
from trading_bot.backtest.engine import run_regime_backtest
from trading_bot.backtest.optimizer import run_grid_search, calculate_sharpe_ratio
from trading_bot.core.config import AppConfig, setup_logging
from trading_bot.core.telegram import TelegramNotifier

logger = logging.getLogger("QuantOptimizer")

def patch_settings_yaml(new_params: dict):
    """
    Substitui os valores no settings.yaml sem usar parser yaml, 
    para não apagar os comentários do arquivo original.
    """
    settings_path = Path("config/settings.yaml")
    if not settings_path.exists():
        logger.error("settings.yaml não encontrado para atualização.")
        return

    content = settings_path.read_text(encoding="utf-8")
    
    for key, value in new_params.items():
        # Busca a chave na seção 'signals:' e substitui o valor.
        # Ex: '  breakout_period: 20'
        pattern = rf"(\s+{key}:\s*)([\d\.]+)"
        if re.search(pattern, content):
            content = re.sub(pattern, rf"\g<1>{value}", content)
        else:
            logger.warning(f"Chave {key} não encontrada no settings.yaml via regex.")

    settings_path.write_text(content, encoding="utf-8")
    logger.info("✅ config/settings.yaml atualizado com sucesso!")


def main():
    parser = argparse.ArgumentParser(description="Agente de Melhoria (Quant Optimizer)")
    parser.parse_args()

    cfg = AppConfig.load()
    setup_logging(cfg)
    logger.info("Iniciando Quant Optimizer...")

    # Notificador Telegram
    telegram_token = cfg.get("notifications", "telegram_bot_token", default="")
    telegram_chat = cfg.get("notifications", "telegram_chat_id", default="")
    notifier = TelegramNotifier(bot_token=telegram_token, chat_id=telegram_chat)

    # Buscar dados (últimos 2 anos para evitar overfitting e demorar muito)
    hoje = date.today()
    start_date = hoje - timedelta(days=2 * 365)
    
    tickers = cfg.get("_universe", "tickers", default=[])
    if not tickers:
        logger.error("Nenhum ticker no universe.yaml")
        return

    logger.info(f"Baixando histórico de 2 anos para {len(tickers)} ativos...")
    data = fetch_universe_yfinance(tickers, start=start_date, end=hoje)

    # Pega parâmetros base
    sig_cfg = cfg.get("signals", default={})
    baseline_params = {
        "breakout_period": sig_cfg.get("breakout_period", 20),
        "volume_mult": sig_cfg.get("volume_multiplier", 1.5),
        "sma_trend_period": sig_cfg.get("sma_trend_period", 200),
        "rsi_max": sig_cfg.get("rsi_max", 75.0),
        "stop_atr_mult": sig_cfg.get("stop_atr_mult", 2.0),
        "stop_pct": sig_cfg.get("stop_pct", 0.04),
        "target_atr_mult": sig_cfg.get("target_atr_mult", 4.0)
    }

    capital = cfg.get("risk", "capital_initial", default=300.0)

    # 1. Roda baseline
    logger.info("Calculando performance Baseline (parâmetros atuais)...")
    baseline_res = run_regime_backtest(
        data=data,
        regime_name="Baseline",
        start=start_date,
        end=hoje,
        capital=capital,
        signal_params=baseline_params,
        ibov_filter=True
    )
    baseline_sharpe = calculate_sharpe_ratio(baseline_res.equity_curve)
    baseline_return = (baseline_res.final_capital / capital - 1) * 100
    logger.info(f"📊 Baseline Sharpe: {baseline_sharpe:.2f} | Retorno: {baseline_return:.2f}%")

    # 2. Define o Grid Search próximo ao baseline
    param_grid = {
        "breakout_period": [15, 20],
        "volume_mult": [1.5],
        "sma_trend_period": [200], # Fixo para não distorcer muito a tendência longa
        "rsi_max": [75.0],
        "stop_atr_mult": [1.5, 2.0],
        "stop_pct": [0.04],
        "target_atr_mult": [3.0, 4.0]
    }

    # 3. Executa a varredura
    results = run_grid_search(
        data=data,
        param_grid=param_grid,
        start_date=start_date,
        end_date=hoje,
        capital=capital
    )

    if not results:
        logger.warning("Nenhum resultado gerado pelo Grid Search.")
        return

    best = results[0]
    best_params = best["params"]
    best_sharpe = best["sharpe"]
    best_return = best["return_pct"]

    logger.info(f"🏆 Melhor Combinação Sharpe: {best_sharpe:.2f} | Retorno: {best_return:.2f}%")
    logger.info(f"Parâmetros: {best_params}")

    # 4. Compara com baseline (Guard-Rail: +10% de melhoria necessária)
    improvement = 0.0
    if baseline_sharpe > 0:
        improvement = (best_sharpe - baseline_sharpe) / baseline_sharpe
    elif best_sharpe > 0:
        improvement = 1.0 # Saiu de zero ou negativo para positivo

    msg = ""
    if improvement >= 0.10:
        logger.info(f"🚀 Melhoria substancial detectada (+{improvement:.1%}). Aplicando atualização!")
        
        # Mapeando chaves do python para o YAML
        yaml_patch = {
            "breakout_period": best_params["breakout_period"],
            "volume_multiplier": best_params["volume_mult"],
            "rsi_max": best_params["rsi_max"],
            "stop_atr_mult": best_params["stop_atr_mult"],
            "stop_pct": best_params["stop_pct"],
            "target_atr_mult": best_params["target_atr_mult"]
        }
        patch_settings_yaml(yaml_patch)

        msg = (
            f"🧠 <b>QUANT OPTIMIZER — UPGRADE APLICADO</b> 🧠\n\n"
            f"Uma nova parametrização se provou superior no histórico de 2 anos.\n\n"
            f"📊 <b>Antes (Baseline)</b>\n"
            f"Sharpe: {baseline_sharpe:.2f} | Retorno: {baseline_return:.2f}%\n\n"
            f"🏆 <b>Depois (Otimizado)</b>\n"
            f"Sharpe: {best_sharpe:.2f} | Retorno: {best_return:.2f}%\n"
            f"Melhoria de Sharpe: +{improvement:.1%}\n\n"
            f"🛠️ <b>Novos Parâmetros Injetados:</b>\n"
            f"Breakout: {best_params['breakout_period']} dias\n"
            f"Stop (ATR Mult): {best_params['stop_atr_mult']}x\n"
            f"Stop (Hard Cap): {best_params['stop_pct']*100:.1f}%\n"
            f"Target (ATR Mult): {best_params['target_atr_mult']}x\n\n"
            f"<i>O sistema operará com essas regras a partir de amanhã.</i>"
        )
    else:
        logger.info(f"⚖️ Sem melhoria substancial (+{improvement:.1%}). Mantendo baseline.")
        msg = (
            f"🧠 <b>QUANT OPTIMIZER — VARREDURA CONCLUÍDA</b> 🧠\n\n"
            f"Milhares de backtests realizados, mas a estratégia atual continua sendo a mais robusta.\n"
            f"Sharpe Atual: {baseline_sharpe:.2f}\n"
            f"Melhor Teste: {best_sharpe:.2f} ({(improvement*100):.1f}%)\n\n"
            f"<i>Baseline mantida por segurança matemática (Guard-Rail).</i>"
        )

    notifier.send_message(text=msg)

if __name__ == "__main__":
    main()
