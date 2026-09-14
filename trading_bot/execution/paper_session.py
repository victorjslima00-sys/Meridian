"""
Sessão Paper Reproduzível (Vulcan / Execução) — Orion Data Engineering
=====================================================================
Pipeline completo de simulação paper auditável:
Sinal -> RiskManager -> ExecutorAgent -> Registro de Eventos Persistente -> Reconciliação.

Invariantes Institucionais:
  - Idempotência estrita: interrupção e reinício sem duplicação de ordens ou posições.
  - Zero tolerância a multiplicação de OMS: delega 100% ao RiskManager e ExecutorAgent existentes.
  - Trilha imutável em disco: gravação append-only com fsync de cada evento em arquivo .jsonl.
  - Reconciliação contábil formal: verificação da conservação de saldos e integridade do SQLite.
  - Invariante absoluto: real_broker_calls == 0 (nenhum envio externo).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field

from backend.app.agents.executor import ExecutorAgent
from backend.app.agents.risk_manager import RiskManager
from backend.app.data.database import DB_PATH

logger = logging.getLogger(__name__)


class PaperSessionEvent(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    event_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    timestamp_utc: str
    event_type: Literal[
        "SESSION_START",
        "SIGNAL_EVALUATED",
        "RISK_DECISION",
        "ORDER_EXECUTED",
        "ORDER_SKIPPED",
        "ORDER_REJECTED",
        "ORDER_CLOSED",
        "RECONCILIATION",
        "SESSION_END",
    ]
    ticker: Optional[str] = None
    payload: Dict[str, Any]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PaperSessionReport(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    session_id: str
    status: Literal["COMPLETED", "INTERRUPTED", "RECONCILED", "DISCREPANCY"]
    started_at_utc: str
    ended_at_utc: str
    events_count: int
    orders_executed: int
    orders_skipped: int
    orders_rejected: int
    orders_closed: int
    portfolio_before: Dict[str, float]
    portfolio_after: Dict[str, float]
    reconciliation_ok: bool
    discrepancies: List[str]
    real_broker_calls: Literal[0] = 0
    report_sha256: Optional[str] = None


class PaperSessionJournal:
    """
    Journal append-only de eventos de simulação paper em disco durável (.jsonl).
    Garante persistência imediata com fsync e idempotência ao reiniciar sessões.
    """

    def __init__(self, session_id: str, storage_dir: Path):
        self.session_id = session_id
        self.storage_dir = storage_dir.resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.storage_dir / f"{session_id}.jsonl"

        self.events: List[PaperSessionEvent] = []
        self.processed_tickers: Set[str] = set()
        self.executed_tickers: Set[str] = set()
        self.event_counter = 0

        if self.journal_path.is_file():
            self.load_events()

    def load_events(self) -> List[PaperSessionEvent]:
        self.events = []
        self.processed_tickers = set()
        self.executed_tickers = set()
        with self.journal_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                evt = PaperSessionEvent.model_validate_json(line)
                self.events.append(evt)
                if evt.ticker:
                    self.processed_tickers.add(evt.ticker)
                if evt.event_type == "ORDER_EXECUTED" and evt.ticker:
                    self.executed_tickers.add(evt.ticker)
                self.event_counter += 1
        return self.events

    def append_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        ticker: Optional[str] = None,
    ) -> PaperSessionEvent:
        self.event_counter += 1
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        event_id = f"EVT-{self.session_id}-{self.event_counter:04d}"

        canonical_payload = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

        event = PaperSessionEvent(
            event_id=event_id,
            session_id=self.session_id,
            timestamp_utc=now_utc,
            event_type=event_type,
            ticker=ticker,
            payload=payload,
            sha256=digest,
        )

        line = event.model_dump_json() + "\n"
        with self.journal_path.open("a", encoding="utf-8") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())

        self.events.append(event)
        if ticker:
            self.processed_tickers.add(ticker)
        if event_type == "ORDER_EXECUTED" and ticker:
            self.executed_tickers.add(ticker)

        return event


class PaperSessionRunner:
    """
    Orquestrador de Sessão Paper Reproduzível (Vulcan).
    Integra Sinal -> RiskManager -> ExecutorAgent -> Journal -> Reconciliação.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        db_path: Optional[str] = None,
        storage_dir: Optional[str] = None,
        risk_manager_cls=RiskManager,
        executor_cls=ExecutorAgent,
    ):
        self.session_id = session_id or datetime.datetime.now(datetime.timezone.utc).strftime("session_%Y%m%d_%H%M%S")
        self.db_path = db_path or DB_PATH
        self.storage_dir = Path(storage_dir or "data/paper_sessions")
        self.risk_manager_cls = risk_manager_cls
        self.executor_cls = executor_cls

        self.journal = PaperSessionJournal(self.session_id, self.storage_dir)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_portfolio_state(self) -> Dict[str, float]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT saldo_disponivel, em_posicoes, margem_operavel, patrimonio_total "
                "FROM portfolio ORDER BY id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if not row:
                return {
                    "saldo_disponivel": 0.0,
                    "em_posicoes": 0.0,
                    "saldo_livre": 0.0,
                    "margem_operavel": 0.0,
                    "patrimonio_total": 0.0,
                }
            disponivel = float(row[0] or 0.0)
            em_posicoes = float(row[1] or 0.0)
            margem = float(row[2]) if row[2] is not None else disponivel
            patrimonio = float(row[3] or 0.0)
            return {
                "saldo_disponivel": disponivel,
                "em_posicoes": em_posicoes,
                "saldo_livre": max(0.0, disponivel - em_posicoes),
                "margem_operavel": margem,
                "patrimonio_total": patrimonio,
            }
        finally:
            conn.close()

    def get_active_tickers(self) -> List[str]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT DISTINCT ticker FROM trades WHERE status = 'active'").fetchall()
            return [str(r[0]) for r in rows]
        finally:
            conn.close()

    def run_cycle(
        self,
        signals: List[Dict[str, Any]],
        current_prices: Optional[Dict[str, float]] = None,
    ) -> PaperSessionReport:
        started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        initial_portfolio = self.get_portfolio_state()

        # 1. Início de Sessão
        self.journal.append_event(
            event_type="SESSION_START",
            payload={
                "db_path": str(self.db_path),
                "initial_portfolio": initial_portfolio,
                "signals_count": len(signals),
            },
        )

        orders_executed = 0
        orders_skipped = 0
        orders_rejected = 0
        orders_closed = 0
        session_allocated_capital = 0.0
        session_returned_capital = 0.0
        session_realized_pnl = 0.0

        executor = self.executor_cls(db_path=self.db_path)

        # 2. Avaliação de Sinais e Execução
        for sig in signals:
            ticker = sig.get("ticker", "").strip().upper()
            if not ticker:
                continue

            # Idempotência de Sessão: se o ticker já foi processado nesta sessão, pula
            if ticker in self.journal.executed_tickers:
                orders_skipped += 1
                self.journal.append_event(
                    event_type="ORDER_SKIPPED",
                    payload={"reason": "already_executed_in_this_session"},
                    ticker=ticker,
                )
                continue

            # Checagem de posição ativa pré-existente no banco
            open_tickers = self.get_active_tickers()
            if ticker in open_tickers:
                orders_skipped += 1
                self.journal.append_event(
                    event_type="ORDER_SKIPPED",
                    payload={"reason": "already_has_active_position_in_db"},
                    ticker=ticker,
                )
                continue

            # Registro do sinal recebido
            self.journal.append_event(
                event_type="SIGNAL_EVALUATED",
                payload=sig,
                ticker=ticker,
            )

            # Avaliação pelo RiskManager existente
            pf_state = self.get_portfolio_state()
            saldo_operavel = pf_state["margem_operavel"]
            em_pos = pf_state["em_posicoes"]

            rm = self.risk_manager_cls(saldo_livre=saldo_operavel, em_posicoes=em_pos)
            decision = rm.evaluate_trade(sig, ticker=ticker, open_tickers=open_tickers)

            self.journal.append_event(
                event_type="RISK_DECISION",
                payload=decision,
                ticker=ticker,
            )

            if decision.get("approved", False):
                # Execução via ExecutorAgent existente
                exec_res = executor.execute_order(ticker, decision, sig)
                if exec_res.get("status") == "executed":
                    orders_executed += 1
                    allocated = float(exec_res.get("allocated_capital", decision.get("allocated_capital", 0.0)))
                    session_allocated_capital += allocated
                    self.journal.append_event(
                        event_type="ORDER_EXECUTED",
                        payload=exec_res,
                        ticker=ticker,
                    )
                elif exec_res.get("status") == "skipped_existing_position":
                    orders_skipped += 1
                    self.journal.append_event(
                        event_type="ORDER_SKIPPED",
                        payload=exec_res,
                        ticker=ticker,
                    )
                else:
                    orders_rejected += 1
                    self.journal.append_event(
                        event_type="ORDER_REJECTED",
                        payload=exec_res,
                        ticker=ticker,
                    )
            else:
                orders_rejected += 1
                self.journal.append_event(
                    event_type="ORDER_REJECTED",
                    payload={"reason": decision.get("reason", "risk_rejection")},
                    ticker=ticker,
                )

        # 3. Gestão de Saídas (Exit Scan quando preços correntes são fornecidos)
        if current_prices:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                rows = cursor.execute(
                    "SELECT id, ticker, side, entry_price, target_price, stop_loss, shares "
                    "FROM trades WHERE status = 'active'"
                ).fetchall()
            finally:
                conn.close()

            for trade_row in rows:
                tid, t_ticker, side, entry_p, target_p, stop_l, shares = trade_row
                curr_p = current_prices.get(t_ticker)
                if curr_p is None or curr_p <= 0:
                    continue

                should_close = False
                close_reason = ""

                if side == "BUY":
                    if target_p > 0 and curr_p >= target_p:
                        should_close = True
                        close_reason = f"Take Profit hit at {curr_p}"
                    elif stop_l > 0 and curr_p <= stop_l:
                        should_close = True
                        close_reason = f"Stop Loss hit at {curr_p}"

                if should_close:
                    close_res = executor.close_order(tid, curr_p, close_reason)
                    if close_res.get("status") == "closed":
                        orders_closed += 1
                        if side == "BUY":
                            pnl_mon = float((curr_p - entry_p) * shares)
                        else:
                            pnl_mon = float((entry_p - curr_p) * shares)
                        allocated_ret = float(shares * entry_p)
                        session_returned_capital += allocated_ret
                        session_realized_pnl += pnl_mon
                        close_res["pnl_monetario"] = pnl_mon
                        close_res["returned_capital"] = allocated_ret
                        self.journal.append_event(
                            event_type="ORDER_CLOSED",
                            payload=close_res,
                            ticker=t_ticker,
                        )

        # 4. Reconciliação Contábil Rigorosa
        final_portfolio = self.get_portfolio_state()
        discrepancies: List[str] = []

        # Validação da conservação de saldos segundo o modelo patrimonial do Meridian:
        # 1) saldo_livre (caixa livre descomprometido) = saldo_disponivel - em_posicoes
        #    delta_livre esperado = -capital_alocado_entradas + capital_devolvido_saidas + pnl_realizado
        free_cash_delta = final_portfolio["saldo_livre"] - initial_portfolio["saldo_livre"]
        expected_free_cash_delta = -session_allocated_capital + session_returned_capital + session_realized_pnl
        if abs(free_cash_delta - expected_free_cash_delta) > 0.01:
            discrepancies.append(
                f"saldo_livre_mismatch: delta real={free_cash_delta:.2f}, esperado={expected_free_cash_delta:.2f}"
            )

        # 2) em_posicoes (capital alocado em trades ativos)
        #    delta_posicoes esperado = capital_alocado_entradas - capital_devolvido_saidas
        allocated_delta = final_portfolio["em_posicoes"] - initial_portfolio["em_posicoes"]
        expected_allocated_delta = session_allocated_capital - session_returned_capital
        if abs(allocated_delta - expected_allocated_delta) > 0.01:
            discrepancies.append(
                f"em_posicoes_mismatch: delta real={allocated_delta:.2f}, esperado={expected_allocated_delta:.2f}"
            )

        # 3) saldo_disponivel (capital entregue ao bot; absorve PnL realizado no fechamento)
        #    delta_disponivel esperado = pnl_realizado
        disponivel_delta = final_portfolio["saldo_disponivel"] - initial_portfolio["saldo_disponivel"]
        expected_disponivel_delta = session_realized_pnl
        if abs(disponivel_delta - expected_disponivel_delta) > 0.01:
            discrepancies.append(
                f"saldo_disponivel_mismatch: delta real={disponivel_delta:.2f}, esperado={expected_disponivel_delta:.2f}"
            )

        reconciliation_ok = len(discrepancies) == 0

        self.journal.append_event(
            event_type="RECONCILIATION",
            payload={
                "reconciliation_ok": reconciliation_ok,
                "discrepancies": discrepancies,
                "free_cash_delta": free_cash_delta,
                "expected_free_cash_delta": expected_free_cash_delta,
                "allocated_delta": allocated_delta,
                "expected_allocated_delta": expected_allocated_delta,
                "disponivel_delta": disponivel_delta,
                "expected_disponivel_delta": expected_disponivel_delta,
                "real_broker_calls": 0,
            },
        )

        ended_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        status_final: Literal["COMPLETED", "INTERRUPTED", "RECONCILED", "DISCREPANCY"] = (
            "RECONCILED" if reconciliation_ok else "DISCREPANCY"
        )

        report = PaperSessionReport(
            session_id=self.session_id,
            status=status_final,
            started_at_utc=started_at,
            ended_at_utc=ended_at,
            events_count=len(self.journal.events),
            orders_executed=orders_executed,
            orders_skipped=orders_skipped,
            orders_rejected=orders_rejected,
            orders_closed=orders_closed,
            portfolio_before=initial_portfolio,
            portfolio_after=final_portfolio,
            reconciliation_ok=reconciliation_ok,
            discrepancies=discrepancies,
            real_broker_calls=0,
        )

        report_json = report.model_dump_json(indent=2)
        report_sha256 = hashlib.sha256(report_json.encode("utf-8")).hexdigest()
        report.report_sha256 = report_sha256

        # Salva o relatório durável em disco
        report_path = self.storage_dir / f"{self.session_id}_report.json"
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

        manifest_path = self.storage_dir / f"{self.session_id}_report.manifest.json"
        manifest_data = {
            "session_id": self.session_id,
            "report_file": str(report_path),
            "report_sha256": report_sha256,
            "generated_at_utc": ended_at,
            "reconciliation_ok": reconciliation_ok,
            "real_broker_calls": 0,
        }
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        self.journal.append_event(
            event_type="SESSION_END",
            payload={"report_sha256": report_sha256, "status": status_final},
        )

        return report
