"""Repository helpers for orders."""

from collections.abc import Sequence
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    Order,
    PlanChange,
    PlannedOperation,
    PlannedOperationDay,
    PlanningConflict,
)


class OrdersRepository:
    """Data access for orders."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_orders(self) -> Sequence[Order]:
        """Return orders ordered by shipment date and ID."""
        return self.session.scalars(
            select(Order).order_by(Order.shipment_date, Order.id)
        ).all()

    def get_order(self, order_id: int) -> Order | None:
        """Return an order by internal ID."""
        return self.session.get(Order, order_id)

    def get_by_number(self, order_number: str) -> Order | None:
        """Return an order by business number."""
        return self.session.scalar(
            select(Order).where(Order.order_number == order_number)
        )

    def create_order(
        self,
        *,
        order_number: str,
        client_name: str,
        product_name: str,
        quantity: float,
        shipment_date: date,
        route_id: int,
        status: str,
    ) -> Order:
        """Create and persist an order."""
        order = Order(
            order_number=order_number,
            client_name=client_name,
            product_name=product_name,
            quantity=quantity,
            shipment_date=shipment_date,
            route_id=route_id,
            status=status,
        )
        self.session.add(order)
        self.session.flush()
        return order

    def update_status(self, order_id: int, status: str) -> Order | None:
        """Update order status."""
        order = self.get_order(order_id)
        if order is None:
            return None
        if order.status != status:
            order.calculated_start_date = None
        order.status = status
        self.session.flush()
        return order

    def update_order(
        self,
        order_id: int,
        *,
        order_number: str,
        client_name: str,
        product_name: str,
        quantity: float,
        shipment_date: date,
        route_id: int,
        status: str,
    ) -> Order | None:
        """Update all editable order fields."""
        order = self.get_order(order_id)
        if order is None:
            return None
        planning_inputs_changed = (
            float(order.quantity) != float(quantity)
            or order.shipment_date != shipment_date
            or order.route_id != route_id
            or order.status != status
        )
        order.order_number = order_number
        order.client_name = client_name
        order.product_name = product_name
        order.quantity = quantity
        order.shipment_date = shipment_date
        order.route_id = route_id
        order.status = status
        if planning_inputs_changed:
            order.calculated_start_date = None
        self.session.flush()
        return order

    def delete_order(self, order_id: int) -> bool:
        """Physically delete an order and all saved planning data tied to it."""
        order = self.get_order(order_id)
        if order is None:
            return False
        planned_operation_ids = select(PlannedOperation.id).where(
            PlannedOperation.order_id == order_id
        )
        self.session.execute(
            delete(PlannedOperationDay).where(
                PlannedOperationDay.planned_operation_id.in_(planned_operation_ids)
            )
        )
        self.session.execute(delete(PlanChange).where(PlanChange.order_id == order_id))
        self.session.execute(
            delete(PlanningConflict).where(PlanningConflict.order_id == order_id)
        )
        self.session.execute(
            delete(PlannedOperation).where(PlannedOperation.order_id == order_id)
        )
        self.session.delete(order)
        self.session.flush()
        return True
