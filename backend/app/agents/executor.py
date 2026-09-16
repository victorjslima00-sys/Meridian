import sqlite3
import datetime
from typing import Dict, Any, Optional
from ..data.database import DB_PATH


class ExecutorAgent:
    def __init__(self, db_path: Optional[str] = None, session_authority: Optional[Any] = None):
        self.db_path = db_path or DB_PATH
        self.session_authority = session_authority

    def _connect(self) -> sqlite3.Connection:
        """Conexão padrão do executor: IMMEDIATE (escreve logo na primeira
        instrução) + busy_timeout, para esperar (em vez de estourar
        'database is locked' na hora) quando outra conexão segura o lock."""
        conn = sqlite3.connect(self.db_path, isolation_level="IMMEDIATE")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def execute_order(self, intent: Any = None, *args, **kwargs) -> Dict[str, Any]:
        """Execute autonomous strategy order. Strictly requires validated ApprovedExecutionIntent."""
        from backend.app.agents.contracts import ApprovedExecutionIntent

        if not isinstance(intent, ApprovedExecutionIntent):
            return {
                "status": "rejected",
                "reason": "Autonomous execution requires a validated ApprovedExecutionIntent",
            }
        try:
            validated_intent = ApprovedExecutionIntent.model_validate(
                intent.model_dump(mode="python")
            )
        except Exception as e:
            return {
                "status": "rejected",
                "reason": f"Authority graph revalidation failed (stale or tampered contract): {e}",
            }
        return self._execute_internal(validated_intent)

    def execute_manual_order(self, intent: Any = None) -> Dict[str, Any]:
        """Execute authenticated manual human order. Strictly requires validated ManualExecutionIntent."""
        from backend.app.agents.contracts import ManualExecutionIntent

        if not isinstance(intent, ManualExecutionIntent):
            return {
                "status": "rejected",
                "reason": "Manual execution requires a validated ManualExecutionIntent",
            }
        try:
            validated_intent = ManualExecutionIntent.model_validate(
                intent.model_dump(mode="python")
            )
        except Exception as e:
            return {
                "status": "rejected",
                "reason": f"Manual authority revalidation failed (stale or tampered contract): {e}",
            }
        return self._execute_internal(validated_intent)

    def _execute_internal(self, intent: Any) -> Dict[str, Any]:
        from backend.app.agents.contracts import ApprovedExecutionIntent, ManualExecutionIntent

        if isinstance(intent, ApprovedExecutionIntent):
            try:
                validated_intent = ApprovedExecutionIntent.model_validate(
                    intent.model_dump(mode="python")
                )
            except Exception as e:
                return {
                    "status": "rejected",
                    "reason": f"Authority graph revalidation failed: {e}",
                }
        elif isinstance(intent, ManualExecutionIntent):
            try:
                validated_intent = ManualExecutionIntent.model_validate(
                    intent.model_dump(mode="python")
                )
            except Exception as e:
                return {
                    "status": "rejected",
                    "reason": f"Manual authority revalidation failed: {e}",
                }
        else:
            return {"status": "rejected", "reason": "Invalid execution intent type"}

        intent = validated_intent

        ticker = intent.ticker
        decision_price = getattr(intent, "decision_price", intent.entry_price)
        execution_price = getattr(intent, "execution_price", intent.entry_price)
        allocated = intent.allocated_capital
        shares = allocated / execution_price if execution_price > 0 else 0
        target_price = intent.target_price
        stop_loss = intent.stop_loss
        side = intent.side
        is_strategy = isinstance(intent, ApprovedExecutionIntent)
        signal_id = intent.signal_id if is_strategy else None
        rationale = f"Strategy Intent (Signal {signal_id})" if is_strategy else f"Manual: {intent.reason}"

        # Autonomous session gate check before write (NEXUS-004-R1 defense in depth)
        if is_strategy:
            from backend.app.markets.b3_session import get_session_authority
            authority = self.session_authority or get_session_authority()
            quote = getattr(intent, "execution_quote", None)
            now_check = getattr(quote, "observed_at", None) if quote else None
            session_allowed, session_reason, _, _ = authority.check_authority(now_check)
            if not session_allowed:
                return {
                    "status": "rejected",
                    "reason": f"Autonomous session gate violation: {session_reason}",
                }

        # Gap geometry check before write (NEXUS-004)
        if is_strategy and side == "BUY":
            if execution_price <= stop_loss or execution_price >= target_price:
                return {
                    "status": "rejected",
                    "reason": f"Gap geometry violation: execution_price {execution_price} outside (stop {stop_loss}, target {target_price})",
                }

        conn = self._connect()
        try:
            cursor = conn.cursor()

            # Signal idempotency check BEFORE opening position check
            if signal_id:
                cursor.execute("SELECT 1 FROM trades WHERE signal_id = ?", (signal_id,))
                if cursor.fetchone():
                    return {
                        "status": "skipped_existing_position",
                        "ticker": ticker,
                        "reason": "Signal already executed (idempotency).",
                    }

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
                cursor.execute("PRAGMA table_info(trades)")
                cols = {row[1] for row in cursor.fetchall()}
                if "decision_price" in cols:
                    cursor.execute(
                        """
                    INSERT INTO trades (ticker, side, shares, entry_price, decision_price, target_price, stop_loss, entry_date, ai_rationale, status, signal_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                    """,
                        (
                            ticker, side, shares, execution_price, decision_price, target_price, stop_loss,
                            datetime.datetime.now(), rationale, signal_id
                        ),
                    )
                else:
                    cursor.execute(
                        """
                    INSERT INTO trades (ticker, side, shares, entry_price, target_price, stop_loss, entry_date, ai_rationale, status, signal_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                    """,
                        (
                            ticker, side, shares, execution_price, target_price, stop_loss,
                            datetime.datetime.now(), rationale, signal_id
                        ),
                    )
            except sqlite3.IntegrityError:
                conn.rollback()
                return {
                    "status": "skipped_existing_position",
                    "ticker": ticker,
                    "reason": "Já existe posição ativa ou sinal repetido (concorrência).",
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
            "price": execution_price,
            "decision_price": decision_price,
            "entry_price": execution_price,
            "total_value": allocated,
        }

    def close_order(
        self,
        trade_id: int,
        current_price: float,
        reason: str,
        evidence: Optional[Any] = None,
    ):
        """
        Closes an active order with finite/positive price validation (NEXUS-004-R1).
        """
        import math
        if current_price is None or isinstance(current_price, bool):
            return {"status": "rejected", "reason": "Exit price cannot be None or bool"}
        try:
            px_val = float(current_price)
        except (TypeError, ValueError):
            return {"status": "rejected", "reason": "Exit price must be real numeric"}
        if not math.isfinite(px_val) or px_val <= 0.0:
            return {"status": "rejected", "reason": f"Exit price must be finite and > 0 (got {current_price})"}

        if evidence is not None:
            from trading_bot.data.valuation_snapshot import compute_evidence_sha256
            if hasattr(evidence, "source_sha256") and hasattr(evidence, "raw_evidence"):
                expected_sha = compute_evidence_sha256(evidence.raw_evidence)
                if evidence.source_sha256 != expected_sha:
                    return {"status": "rejected", "reason": "Exit quote evidence hash mismatch"}
            if hasattr(evidence, "observed_at") and getattr(evidence.observed_at, "tzinfo", None) is None:
                return {"status": "rejected", "reason": "Exit quote timestamp cannot be naive"}

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
                    pnl_pct = ((px_val - entry_price) / entry_price) * 100
                else:
                    pnl_pct = ((entry_price - px_val) / entry_price) * 100
            else:
                pnl_pct = 0.0

            gross_value = shares * px_val

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
                (px_val, datetime.datetime.now(), pnl_pct, reason, trade_id),
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
