"""Repository helpers for orders."""

from collections.abc import Sequence
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.constants import (
    CALCULATED_ORDER_STATUSES,
    PLANNING_MODE_SHIPMENT,
    MANUAL_ORDER_STATUSES,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_NEW,
)
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
        """Return orders in their user-defined planning order."""
        return self.session.scalars(
            select(Order).order_by(Order.priority == 0, Order.priority, Order.id)
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
        shipment_date: date | None,
        route_id: int,
        status: str = ORDER_STATUS_NEW,
        planning_mode: str = PLANNING_MODE_SHIPMENT,
        fixed_start_date: date | None = None,
        child_group_key: str | None = None,
        child_sequence_number: int | None = None,
        is_child_order: bool = False,
        is_linked_child_group: bool = False,
        priority: int | None = None,
    ) -> Order:
        """Create and persist an order."""
        if status != ORDER_STATUS_NEW:
            raise ValueError("New orders can only be created with status 'Новый'.")
        if priority is None:
            priority = int(self.session.scalar(select(func.max(Order.priority))) or 0) + 1
        order = Order(
            priority=priority,
            order_number=order_number,
            client_name=client_name,
            product_name=product_name,
            quantity=quantity,
            shipment_date=shipment_date,
            route_id=route_id,
            status=status,
            planning_mode=planning_mode,
            fixed_start_date=fixed_start_date,
            child_group_key=child_group_key,
            child_sequence_number=child_sequence_number,
            is_child_order=is_child_order,
            is_linked_child_group=is_linked_child_group,
        )
        self.session.add(order)
        self.session.flush()
        return order

    def update_status(self, order_id: int, status: str) -> Order | None:
        """Update order status."""
        order = self.get_order(order_id)
        if order is None:
            return None
        self._validate_manual_status(status)
        if order.status != status:
            order.calculated_start_date = None
        order.status = status
        if status == ORDER_STATUS_CANCELLED:
            order.calculated_start_date = None
            self._clear_order_conflicts(order_id)
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
        shipment_date: date | None,
        route_id: int,
        status: str,
        planning_mode: str = PLANNING_MODE_SHIPMENT,
        fixed_start_date: date | None = None,
        child_group_key: str | None = None,
        child_sequence_number: int | None = None,
        is_child_order: bool = False,
        is_linked_child_group: bool = False,
        priority: int | None = None,
    ) -> Order | None:
        """Update all editable order fields."""
        order = self.get_order(order_id)
        if order is None:
            return None
        original_status = order.status
        self._validate_manual_status(status, current_status=original_status)
        planning_inputs_changed = (
            float(order.quantity) != float(quantity)
            or order.shipment_date != shipment_date
            or order.route_id != route_id
            or order.status != status
            or order.planning_mode != planning_mode
            or order.fixed_start_date != fixed_start_date
        )
        order.order_number = order_number
        order.client_name = client_name
        order.product_name = product_name
        order.quantity = quantity
        order.shipment_date = shipment_date
        order.route_id = route_id
        order.status = status
        order.planning_mode = planning_mode
        order.fixed_start_date = fixed_start_date
        order.child_group_key = child_group_key
        order.child_sequence_number = child_sequence_number
        order.is_child_order = is_child_order
        order.is_linked_child_group = is_linked_child_group
        if priority is not None:
            order.priority = priority
        self.session.flush()
        return order

    @staticmethod
    def _validate_manual_status(
        status: str, *, current_status: str | None = None
    ) -> None:
        if status in MANUAL_ORDER_STATUSES:
            return
        # Empty is a system-owned result state.  It may be submitted unchanged
        # by the editor, but cannot be assigned to another order manually.
        if status in ("", None) and current_status in ("", None):
            return
        if status == current_status and status in CALCULATED_ORDER_STATUSES:
            return
        raise ValueError(
            "Статус 'Запланирован' назначается только после пересчёта; вручную можно назначить только 'Новый' или 'Отменён'."
        )

    def _clear_order_conflicts(self, order_id: int) -> None:
        self.session.execute(
            delete(PlanningConflict).where(PlanningConflict.order_id == order_id)
        )

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
