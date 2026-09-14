"""
Testes unitarios para o Sistema de Gestao de Ordens e Reconciliacao (OMS) — Orion Execution
"""
import pytest
from trading_bot.execution.order_manager import OrderManagementSystem, Order, OrderStatus, OrderSide


def test_order_lifecycle():
    oms = OrderManagementSystem()
    order = oms.create_order(ticker="PETR4", side=OrderSide.BUY, quantity=100, price=35.50)
    
    assert order.status == OrderStatus.PENDING
    assert order.order_id.startswith("ORD-")

    # Atualiza para parcialmente executada
    oms.update_order_status(order.order_id, OrderStatus.PARTIALLY_FILLED, filled_quantity=50)
    o = oms.get_order(order.order_id)
    assert o.status == OrderStatus.PARTIALLY_FILLED
    assert o.filled_quantity == 50

    # Atualiza para totalmente executada
    oms.update_order_status(order.order_id, OrderStatus.FILLED, filled_quantity=100)
    o = oms.get_order(order.order_id)
    assert o.status == OrderStatus.FILLED
    assert o.filled_quantity == 100


def test_portfolio_reconciliation():
    oms = OrderManagementSystem()
    # Posições internas do robô
    internal_positions = {"PETR4": 100, "VALE3": 200}
    
    # Custódia da corretora com divergência em VALE3
    broker_positions = {"PETR4": 100, "VALE3": 180, "ITUB4": 50}
    
    recon = oms.reconcile_positions(internal_positions, broker_positions)
    assert recon["has_discrepancy"] is True
    assert "VALE3" in recon["discrepancies"]
    assert recon["discrepancies"]["VALE3"]["delta"] == -20
    assert "ITUB4" in recon["unexpected_broker_positions"]
