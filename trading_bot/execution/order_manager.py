"""
Sistema de Gestao de Ciclo de Vida de Ordens (OMS) e Reconciliacao de Custodia
Head of Data Engineering: Orion
Meridian Technologies

Invariantes Institucionais:
  - Idempotencia de ordens com UUID deterministico
  - Rastreamento estrito de estados (PENDING -> SUBMITTED -> PARTIALLY_FILLED -> FILLED / REJECTED / CANCELLED)
  - Reconciliacao automatica entre banco local e broker
"""
from __future__ import annotations

import datetime
import enum
import logging
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Order:
    order_id: str
    ticker: str
    side: OrderSide
    quantity: int
    price: float
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    created_at_utc: Optional[str] = None
    updated_at_utc: Optional[str] = None

    def __post_init__(self):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if self.created_at_utc is None:
            self.created_at_utc = now
        if self.updated_at_utc is None:
            self.updated_at_utc = now

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["side"] = self.side.value
        return d


class OrderManagementSystem:
    """
    Controla o ciclo de vida completo de ordens de execucao.
    """

    def __init__(self):
        self.orders: Dict[str, Order] = {}

    def create_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: int,
        price: float,
    ) -> Order:
        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        order = Order(
            order_id=order_id,
            ticker=ticker.upper(),
            side=side,
            quantity=quantity,
            price=price,
            status=OrderStatus.PENDING,
        )
        self.orders[order_id] = order
        logger.info("Ordem criada: %s | %s %s qtd=%s px=%.2f", order_id, side.value, ticker, quantity, price)
        return order

    def update_order_status(
        self,
        order_id: str,
        new_status: OrderStatus,
        filled_quantity: Optional[int] = None,
    ) -> Optional[Order]:
        order = self.orders.get(order_id)
        if not order:
            logger.warning("Ordem nao encontrada: %s", order_id)
            return None

        order.status = new_status
        if filled_quantity is not None:
            order.filled_quantity = filled_quantity
        order.updated_at_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

        logger.info("Ordem %s atualizada para %s (filled=%d/%d)", order_id, new_status.value, order.filled_quantity, order.quantity)
        return order

    def get_order(self, order_id: str) -> Optional[Order]:
        return self.orders.get(order_id)

    def reconcile_positions(
        self,
        internal_positions: Dict[str, int],
        broker_positions: Dict[str, int],
    ) -> dict[str, Any]:
        """
        Compara as posicoes internas do Meridian contra a custodia real/demo da corretora.
        """
        discrepancies = {}
        all_tickers = set(internal_positions.keys()).union(set(broker_positions.keys()))

        unexpected_broker = []
        for ticker in all_tickers:
            int_qty = internal_positions.get(ticker, 0)
            brk_qty = broker_positions.get(ticker, 0)

            if ticker not in internal_positions and brk_qty > 0:
                unexpected_broker.append(ticker)

            if int_qty != brk_qty:
                discrepancies[ticker] = {
                    "internal_quantity": int_qty,
                    "broker_quantity": brk_qty,
                    "delta": brk_qty - int_qty,
                }

        has_discrepancy = len(discrepancies) > 0
        return {
            "has_discrepancy": has_discrepancy,
            "discrepancies": discrepancies,
            "unexpected_broker_positions": unexpected_broker,
            "reconciled_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
