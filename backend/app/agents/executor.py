import sqlite3
import datetime
from typing import Dict, Any
from ..data.database import DB_PATH


class ExecutorAgent:
    def __init__(self):
        self.db_path = DB_PATH

    def _connect(self) -> sqlite3.Connection:
        """Conexão padrão do executor: IMMEDIATE (escreve logo na primeira
        instrução) + busy_timeout, para esperar (em vez de estourar
        'database is locked' na hora) quando outra conexão segura o lock."""
        conn = sqlite3.connect(self.db_path, isolation_level="IMMEDIATE")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def execute_order(
        self, ticker: str, decision: Dict[str, Any], analysis: Dict[str, Any]
    ):
        """
        Simulates an execution through our 'Paper Trading' broker.
        Writes the trade to the database.
        """
        if not decision.get("approved", False):
            return {"status": "rejected", "reason": "Not approved by risk manager."}

        current_price = analysis.get("last_price", 0.0)
        allocated = decision.get("allocated_capital", 0.0)
        shares = allocated / current_price if current_price > 0 else 0

        target_price = decision.get("target_price", 0.0)
        stop_loss = decision.get("stop_loss", 0.0)
        analyst_reason = analysis.get("reason", "N/A")
        rm_reason = decision.get("reason", "N/A")
        rationale = f"{analyst_reason} | {rm_reason}"
        side = analysis.get("signal", "BUY")

        conn = self._connect()
        try:
            cursor = conn.cursor()

            # Guarda transacional (early-exit): checagem dentro da mesma
            # transação IMMEDIATE, evita tentar o INSERT no caso comum.
            # Sozinha ela é raçosa (TOCTOU: duas conexões podem passar aqui
            # "ao mesmo tempo" antes de qualquer uma escrever) — quem
            # realmente garante 1-ativo-por-ticker é o índice único parcial
            # abaixo, via IntegrityError.
            cursor.execute(
                "SELECT 1 FROM trades WHERE ticker = ? AND status = 'active'",
                (ticker,),
            )
            if cursor.fetchone():
                return {
                    "status": "skipped_existing_position",
                    "ticker": ticker,
                    "reason": "Já existe posição ativa para este ticker.",
                }

            try:
                cursor.execute(
                    """
                INSERT INTO trades (ticker, side, shares, entry_price, target_price, stop_loss, entry_date, ai_rationale, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                    (
                        ticker,
                        side,
                        shares,
                        current_price,
                        target_price,
                        stop_loss,
                        datetime.datetime.now(),
                        rationale,
                    ),
                )
            except sqlite3.IntegrityError:
                # Backstop do índice único: outra conexão venceu a corrida
                # entre a checagem acima e este INSERT. O BEGIN IMMEDIATE já
                # foi disparado por essa tentativa de INSERT (mesmo falha),
                # então a transação segue aberta segurando o lock de escrita
                # até fecharmos — rollback explícito libera na hora, em vez
                # de depender do close() implícito no finally.
                conn.rollback()
                return {
                    "status": "skipped_existing_position",
                    "ticker": ticker,
                    "reason": "Já existe posição ativa para este ticker (concorrência).",
                }

            # Deduct from portfolio
            cursor.execute(
                "SELECT id, saldo_disponivel, em_posicoes, margem_operavel "
                "FROM portfolio ORDER BY id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                pid, disponivel, em_pos, margem_operavel = row
                livre = disponivel - em_pos
                if allocated > livre:
                    # Caso extremo onde a alocação excede o livre no momento exato da execução
                    # Na prática o risk_manager deveria ter barrado, mas barramos aqui por segurança
                    conn.rollback()
                    return {
                        "status": "rejected",
                        "reason": f"Capital livre insuficiente (Livre: {livre:.2f}, Req: {allocated:.2f})",
                    }

                # usabilidade 2e — portão de capital de TODA entrada (laço
                # automático e manual afunilam aqui): com margem_operavel
                # definida, a exposição total (em_posicoes + alocação) nunca
                # passa do teto. Checado dentro da MESMA transação IMMEDIATE
                # que lê em_posicoes — sem TOCTOU com outra entrada
                # concorrente. Tolerância de 1e-9 só para ruído de float;
                # o teto é inclusivo (exatamente na margem é aceito).
                if margem_operavel is not None and em_pos + allocated > margem_operavel + 1e-9:
                    conn.rollback()
                    return {
                        "status": "rejected",
                        "reason": (
                            f"Margem operável excedida (teto: {margem_operavel:.2f}, "
                            f"exposição atual: {em_pos:.2f}, ordem: {allocated:.2f})"
                        ),
                    }

                new_em_pos = em_pos + allocated
                cursor.execute(
                    """
                UPDATE portfolio SET em_posicoes = ?, updated_at = ? WHERE id = ?
                """,
                    (new_em_pos, datetime.datetime.now(), pid),
                )

            conn.commit()
        finally:
            conn.close()

        return {
            "status": "executed",
            "ticker": ticker,
            "shares": shares,
            "price": current_price,
            "total_value": allocated,
        }

    def close_order(self, trade_id: int, current_price: float, reason: str):
        """
        Closes an active order.
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT ticker, side, shares, entry_price FROM trades WHERE id = ?",
                (trade_id,),
            )
            row = cursor.fetchone()
            if not row:
                return {"status": "error", "reason": "Trade not found."}

            ticker, side, shares, entry_price = row

            # Calculate PnL
            if entry_price > 0:
                if side == "BUY":
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100
                else:
                    pnl_pct = ((entry_price - current_price) / entry_price) * 100
            else:
                pnl_pct = 0.0

            gross_value = shares * current_price

            # CAS: só transiciona quem está 'active' agora, dentro desta
            # mesma transação IMMEDIATE. rowcount é a fonte de verdade —
            # não o valor de status lido no SELECT acima (que pode já estar
            # obsoleto se outra conexão fechou o trade entre o SELECT e
            # este UPDATE).
            cursor.execute(
                """
            UPDATE trades
            SET status = 'closed', exit_price = ?, exit_date = ?, pnl_pct = ?, exit_reason = ?
            WHERE id = ? AND status = 'active'
            """,
                (current_price, datetime.datetime.now(), pnl_pct, reason, trade_id),
            )
            if cursor.rowcount == 0:
                # Perdemos a corrida (ou já estava fechado antes desta
                # chamada). O UPDATE não afetou nenhuma linha, mas a
                # transação IMMEDIATE segue aberta — rollback explícito
                # libera o lock imediatamente. Não credita o portfolio.
                conn.rollback()
                return {"status": "already_closed", "trade_id": trade_id}

            # Update portfolio
            cursor.execute(
                "SELECT id, saldo_disponivel, em_posicoes FROM portfolio ORDER BY id DESC LIMIT 1"
            )
            pf_row = cursor.fetchone()
            if pf_row:
                pid, disponivel, em_pos = pf_row

                # PnL logic on capital
                original_allocation = shares * entry_price
                return_value = gross_value

                # Devolve o capital alocado e o lucro/prejuízo para o saldo disponível
                new_em_pos = max(0.0, em_pos - original_allocation)
                new_disponivel = disponivel - original_allocation + return_value

                cursor.execute(
                    """
                UPDATE portfolio SET saldo_disponivel = ?, em_posicoes = ?, updated_at = ? WHERE id = ?
                """,
                    (new_disponivel, new_em_pos, datetime.datetime.now(), pid),
                )

            conn.commit()
        finally:
            conn.close()

        return {
            "status": "closed",
            "trade_id": trade_id,
            "ticker": ticker,
            "exit_price": current_price,
            "pnl_pct": pnl_pct,
        }
