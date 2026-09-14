#!/usr/bin/env python3
"""
CLI Runner — Sessão Paper Reproduzível (Vulcan / Execução)
=========================================================
Executa uma sessão paper auditável com persistência incremental de eventos,
idempotência de ordens e reconciliação contábil formal.
Invariante: Zero chamadas a corretoras reais (real_broker_calls == 0).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

# Garante raiz no sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from trading_bot.execution.paper_session import PaperSessionRunner, PaperSessionReport

logger = logging.getLogger("run_paper_session")


def format_report_table(report: PaperSessionReport) -> str:
    lines = [
        "+--------------------------------------------------------------------------------+",
        "|                 MERIDIAN / VULCAN — SESSÃO PAPER AUDITÁVEL                     |",
        "+--------------------------------------------------------------------------------+",
        f"| Identificador da Sessão : {report.session_id:<52} |",
        f"| Status da Reconciliação : {report.status:<52} |",
        f"| Início (UTC)            : {report.started_at_utc:<52} |",
        f"| Término (UTC)           : {report.ended_at_utc:<52} |",
        f"| Eventos Registrados     : {report.events_count:<52} |",
        "+--------------------------------------------------------------------------------+",
        "| OPERAÇÕES DA SESSÃO                                                            |",
        f"|   - Ordens Executadas   : {report.orders_executed:<52} |",
        f"|   - Ordens Ignoradas    : {report.orders_skipped:<52} |",
        f"|   - Ordens Rejeitadas   : {report.orders_rejected:<52} |",
        f"|   - Ordens Encerradas   : {report.orders_closed:<52} |",
        "+--------------------------------------------------------------------------------+",
        "| ESTADO PATRIMONIAL                                                             |",
        f"|   - Saldo Inicial Disp. : R$ {report.portfolio_before.get('saldo_disponivel', 0.0):<49.2f} |",
        f"|   - Saldo Final Disp.   : R$ {report.portfolio_after.get('saldo_disponivel', 0.0):<49.2f} |",
        f"|   - Em Posições Final   : R$ {report.portfolio_after.get('em_posicoes', 0.0):<49.2f} |",
        "+--------------------------------------------------------------------------------+",
        "| GOVERNANÇA E AUDITORIA                                                         |",
        f"|   - Reconciliação Conforme : {str(report.reconciliation_ok).upper():<50} |",
        f"|   - Chamadas a Broker Real : {report.real_broker_calls:<52} |",
        f"|   - SHA-256 do Relatório   : {str(report.report_sha256)[:52]:<52} |",
        "+--------------------------------------------------------------------------------+",
    ]
    if report.discrepancies:
        lines.append("| DISCREPÂNCIAS DETECTADAS:")
        for disc in report.discrepancies:
            lines.append(f"|   ! {disc}")
        lines.append("+--------------------------------------------------------------------------------+")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Runner de Sessão Paper Reproduzível (Vulcan)")
    parser.add_argument("--session-id", type=str, default=None, help="ID da sessão paper (opcional)")
    parser.add_argument("--db-path", type=str, default=None, help="Caminho do banco SQLite")
    parser.add_argument("--storage-dir", type=str, default="data/paper_sessions", help="Diretório de logs/relatórios")
    parser.add_argument("--quiet", action="store_true", help="Suprime logs informativos")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    runner = PaperSessionRunner(
        session_id=args.session_id,
        db_path=args.db_path,
        storage_dir=args.storage_dir,
    )

    logger.info("Iniciando ciclo paper determinístico para a sessão %s...", runner.session_id)

    # Exemplo de sinais estruturados para execução da sessão
    signals = [
        {
            "ticker": "PETR4",
            "signal": "BUY",
            "last_price": 38.50,
            "target_price": 42.00,
            "stop_loss": 36.50,
            "confidence": 85,
            "reason": "Donchian 20d Breakout + SMA-200 Bull Trend",
        },
        {
            "ticker": "VALE3",
            "signal": "BUY",
            "last_price": 61.20,
            "target_price": 67.00,
            "stop_loss": 58.00,
            "confidence": 80,
            "reason": "Volume Surge Breakout Confirmation",
        },
    ]

    report = runner.run_cycle(signals=signals)
    print("\n" + format_report_table(report))

    return 0 if report.reconciliation_ok else 1


if __name__ == "__main__":
    sys.exit(main())
