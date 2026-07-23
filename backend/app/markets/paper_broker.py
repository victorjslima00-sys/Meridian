"""
PaperBroker — implementação de Broker sobre o ExecutorAgent (Fase 1,
Commit 1).

Delegação pura para `backend/app/agents/executor.py`, que já contém tudo
que importa e é o único lugar que escreve trades/portfolio: CAS no
fechamento, índice único de 1-ativo-por-ticker, teto de margem operável,
tudo dentro de transações IMMEDIATE. Nada disso se move para cá — este
arquivo só dá ao executor a FORMA de uma corretora, para que uma
corretora real (Cedro) possa ocupar o mesmo encaixe depois.

Instancia o ExecutorAgent por chamada, igual ao código atual faz
(`executor = ExecutorAgent()` em cada ponto de uso). O agente é sem
estado — guarda só o db_path — então isso preserva o comportamento
exatamente, inclusive relendo DB_PATH a cada operação (o que os testes
que trocam DB_PATH dependem).
"""
from __future__ import annotations

from typing import Any


class PaperBroker:
    """Corretora simulada (paper trading local em SQLite)."""

    name = "paper"

    def _agent(self):
        # Import tardio + instância por chamada: mantém a leitura de
        # DB_PATH no momento da operação, como no código atual.
        from ..agents.executor import ExecutorAgent

        return ExecutorAgent()

    def execute_order(
        self, ticker: str, decision: dict[str, Any], analysis: dict[str, Any]
    ) -> dict[str, Any]:
        return self._agent().execute_order(ticker, decision, analysis)

    def close_order(
        self, trade_id: int, current_price: float, reason: str
    ) -> dict[str, Any]:
        return self._agent().close_order(trade_id, current_price, reason)
