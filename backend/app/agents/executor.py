import sqlite3
import datetime
from typing import Dict, Any, Optional
from ..data.database import DB_PATH


class ExecutorAgent:
    def __init__(self, db_path: Optional[str] = None, session_authority: Optional[Any] = None, *, validation_context=None):
        from copy import deepcopy
        from .contracts import approval_lookup_context
        approval_lookup_context(validation_context)
        self._validation_context = deepcopy(validation_context)
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
                intent.model_dump(mode="python"), context=self._validation_context
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
                    intent.model_dump(mode="python"), context=self._validation_context
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

        # Autonomous session gate check before write (NEXUS-004-R1 / R2 defense in depth)
        if is_strategy:
            from backend.app.markets.b3_session import get_session_authority
            authority = self.session_authority or get_session_authority()
            # 1. Evaluate current execution clock (must be CONTINUOUS right now at execution time)
            session_allowed, session_reason, _, _ = authority.check_authority(None)
            if not session_allowed:
                return {
                    "status": "rejected",
                    "reason": f"Autonomous session gate violation: {session_reason}",
                }
            # 2. Evaluate quote observation time (quote must have been observed during CONTINUOUS phase)
            quote = getattr(intent, "execution_quote", None)
            if quote and getattr(quote, "observed_at", None):
                quote_allowed, quote_reason, _, _ = authority.check_authority(quote.observed_at)
                if not quote_allowed:
                    return {
                        "status": "rejected",
                        "reason": f"Autonomous session gate violation on quote observation: {quote_reason}",
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
        max_observation_age_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Closes an active order with strict evidence validation (NEXUS-004-R3).
        Any market-price-driven Paper accounting close MUST require explicit,
        validated market evidence at this final mutation boundary.
        Failure produces 0 trade mutation and 0 portfolio mutation.
        """
        import math
        # 1. Price validation
        if current_price is None or isinstance(current_price, bool) or type(current_price).__name__ in ("bool", "bool_"):
            return {"status": "rejected", "reason": "Exit price cannot be None or bool"}
        try:
            px_val = float(current_price)
        except (TypeError, ValueError):
            return {"status": "rejected", "reason": "Exit price must be real numeric"}
        if not math.isfinite(px_val) or px_val <= 0.0:
            return {"status": "rejected", "reason": f"Exit price must be finite and > 0 (got {current_price})"}

        # 2. Evidence must be provided
        if evidence is None:
            return {"status": "rejected", "reason": "Exit price evidence is required for market close"}

        from trading_bot.data.valuation_snapshot import (
            EvidencedQuote,
            PAPER_DEFAULT_MAX_QUOTE_AGE_SECONDS,
            compute_evidence_sha256,
        )
        if not isinstance(evidence, EvidencedQuote):
            return {"status": "rejected", "reason": "Evidence must be an instance of EvidencedQuote"}

        try:
            validated_evidence = EvidencedQuote.model_validate(evidence.model_dump(mode="python"))
        except Exception as e:
            return {"status": "rejected", "reason": f"Invalid EvidencedQuote structure: {e}"}

        ev_px = validated_evidence.price
        if ev_px is None or isinstance(ev_px, bool) or type(ev_px).__name__ in ("bool", "bool_"):
            return {"status": "rejected", "reason": "Evidence price cannot be None or bool"}
        try:
            ev_px_val = float(ev_px)
        except (TypeError, ValueError):
            return {"status": "rejected", "reason": "Evidence price must be real numeric"}
        if not math.isfinite(ev_px_val) or ev_px_val <= 0.0:
            return {"status": "rejected", "reason": f"Evidence price must be finite and > 0 (got {ev_px})"}

        if abs(px_val - ev_px_val) > 1e-6:
            return {
                "status": "rejected",
                "reason": f"Execution price {px_val} does not match evidence price {ev_px_val}",
            }

        # 3. Timestamps & freshness validation
        obs_at = validated_evidence.observed_at
        col_at = validated_evidence.collected_at
        if obs_at is None or getattr(obs_at, "tzinfo", None) is None:
            return {"status": "rejected", "reason": "Exit quote observation timestamp cannot be naive"}
        if col_at is None or getattr(col_at, "tzinfo", None) is None:
            return {"status": "rejected", "reason": "Exit quote collection timestamp cannot be naive"}

        if obs_at > col_at + datetime.timedelta(seconds=1.0):
            return {
                "status": "rejected",
                "reason": f"Exit quote observed_at ({obs_at}) is materially after collected_at ({col_at})",
            }

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        obs_utc = obs_at.astimezone(datetime.timezone.utc)
        col_utc = col_at.astimezone(datetime.timezone.utc)
        tolerated_skew = 5.0
        if (obs_utc - now_utc).total_seconds() > tolerated_skew or (col_utc - now_utc).total_seconds() > tolerated_skew:
            return {"status": "rejected", "reason": "Exit quote timestamp cannot be in the future"}

        if max_observation_age_seconds is None:
            effective_max_age = float(PAPER_DEFAULT_MAX_QUOTE_AGE_SECONDS)
        else:
            if isinstance(max_observation_age_seconds, bool) or type(max_observation_age_seconds).__name__ in ("bool", "bool_"):
                return {"status": "rejected", "reason": "max_observation_age_seconds cannot be bool"}
            if not isinstance(max_observation_age_seconds, (int, float)):
                return {"status": "rejected", "reason": "max_observation_age_seconds must be numeric"}
            try:
                effective_max_age = float(max_observation_age_seconds)
            except (TypeError, ValueError):
                return {"status": "rejected", "reason": "max_observation_age_seconds must be numeric"}
            if not math.isfinite(effective_max_age) or effective_max_age <= 0.0:
                return {
                    "status": "rejected",
                    "reason": f"max_observation_age_seconds must be finite and > 0 (got {max_observation_age_seconds})",
                }

        observation_age = (now_utc - obs_utc).total_seconds()
        if observation_age > effective_max_age:
            return {
                "status": "rejected",
                "reason": f"Exit quote observation is stale ({observation_age:.1f}s > {effective_max_age}s)",
            }

        collection_age = (now_utc - col_utc).total_seconds()
        if collection_age > effective_max_age:
            return {
                "status": "rejected",
                "reason": f"Exit quote collection is stale ({collection_age:.1f}s > {effective_max_age}s)",
            }

        # 4. Evidence hash and semantic binding
        expected_sha = compute_evidence_sha256(validated_evidence.raw_evidence)
        if validated_evidence.source_sha256 != expected_sha:
            return {"status": "rejected", "reason": "Exit quote evidence hash mismatch"}

        raw_ev = validated_evidence.raw_evidence or {}
        raw_close = raw_ev.get("close")
        if raw_close is None or isinstance(raw_close, bool) or type(raw_close).__name__ in ("bool", "bool_"):
            return {"status": "rejected", "reason": "Raw evidence close is missing or bool"}
        try:
            raw_close_val = float(raw_close)
        except (TypeError, ValueError):
            return {"status": "rejected", "reason": "Raw evidence close must be real numeric"}
        if not math.isfinite(raw_close_val) or raw_close_val <= 0.0:
            return {
                "status": "rejected",
                "reason": f"Raw evidence close must be finite and > 0 (got {raw_close_val})",
            }
        if abs(raw_close_val - ev_px_val) > 1e-6:
            return {
                "status": "rejected",
                "reason": f"Raw evidence close {raw_close_val} does not match evidence price {ev_px_val}",
            }

        def _canonical(t: str) -> str:
            return str(t).replace(".SA", "").strip().upper()

        if _canonical(raw_ev.get("ticker", "")) != _canonical(validated_evidence.ticker):
            return {
                "status": "rejected",
                "reason": f"Raw evidence ticker {raw_ev.get('ticker')} does not match evidence ticker {validated_evidence.ticker}",
            }

        conn = self._connect()
        try:
            cursor = conn.cursor()

            # 5. Load active trade BEFORE authorizing evidence ticker
            cursor.execute(
                "SELECT ticker, side, shares, entry_price, status FROM trades WHERE id = ?",
                (trade_id,),
            )
            row = cursor.fetchone()
            if not row:
                return {"status": "error", "reason": "Trade not found."}

            ticker, side, shares, entry_price, status = row
            if status != "active":
                return {"status": "already_closed", "trade_id": trade_id}

            if _canonical(validated_evidence.ticker) != _canonical(ticker):
                return {
                    "status": "rejected",
                    "reason": f"Exit evidence ticker {validated_evidence.ticker} does not match trade ticker {ticker}",
                }

            # Calculate PnL
            if entry_price > 0:
                if side == "BUY":
                    pnl_pct = ((px_val - entry_price) / entry_price) * 100
                else:
                    pnl_pct = ((entry_price - px_val) / entry_price) * 100
            else:
                pnl_pct = 0.0

            gross_value = shares * px_val

            # CAS: transition only if still 'active' inside this IMMEDIATE transaction
            cursor.execute(
                """
            UPDATE trades
            SET status = 'closed', exit_price = ?, exit_date = ?, pnl_pct = ?, exit_reason = ?
            WHERE id = ? AND status = 'active'
            """,
                (px_val, datetime.datetime.now(), pnl_pct, reason, trade_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return {"status": "already_closed", "trade_id": trade_id}

            # Update portfolio
            cursor.execute(
                "SELECT id, saldo_disponivel, em_posicoes FROM portfolio ORDER BY id DESC LIMIT 1"
            )
            pf_row = cursor.fetchone()
            if pf_row:
                pid, disponivel, em_pos = pf_row
                original_allocation = shares * entry_price
                return_value = gross_value
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
            "exit_price": px_val,
            "pnl_pct": pnl_pct,
        }

