from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class OrderStatus(Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

@dataclass
class Order:
    ticker: str
    side: str
    qty: int
    price: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    id: Optional[int] = None

class BaseBroker(ABC):
    @abstractmethod
    def submit_order(self, ticker: str, side: str, qty: int, price: Optional[float] = None, stop: Optional[float] = None, target: Optional[float] = None) -> Order:
        pass

    @abstractmethod
    def cancel_order(self, order_id: int) -> bool:
        pass
