"""CRUD-style catalog operations used by Streamlit forms."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.constants import ORDER_STATUS_NEW
from app.db.models import Order, Route, RouteOperation, WorkCenter


class CatalogService:
    """Application service for manual MVP data entry."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_work_center(self, *, name: str, available_hours_per_day: float, is_active: bool = True) -> WorkCenter:
        """Create a production work center with positive daily capacity."""
        _require_text(name, "Название участка")
        if available_hours_per_day <= 0:
            raise ValueError("Доступные часы участка должны быть больше 0.")
        work_center = WorkCenter(name=name.strip(), available_hours_per_day=available_hours_per_day, is_active=is_active)
        self.session.add(work_center)
        self.session.commit()
        return work_center

    def create_route(self, *, name: str, description: str | None = None, is_active: bool = True) -> Route:
        """Create a technological route."""
        _require_text(name, "Название маршрута")
        route = Route(name=name.strip(), description=(description or "").strip() or None, is_active=is_active)
        self.session.add(route)
        self.session.commit()
        return route

    def add_route_operation(
        self,
        *,
        route_id: int,
        work_center_id: int,
        sequence_number: int,
        labor_hours_per_1000: float,
        min_transfer_quantity_to_next: float | None = None,
    ) -> RouteOperation:
        """Add an operation to a route."""
        if sequence_number <= 0:
            raise ValueError("Порядковый номер операции должен быть больше 0.")
        if labor_hours_per_1000 <= 0:
            raise ValueError("Трудоёмкость операции должна быть больше 0.")
        if min_transfer_quantity_to_next is not None and min_transfer_quantity_to_next <= 0:
            raise ValueError("Передаточная партия должна быть больше 0.")
        operation = RouteOperation(
            route_id=route_id,
            work_center_id=work_center_id,
            sequence_number=sequence_number,
            labor_hours_per_1000=labor_hours_per_1000,
            min_transfer_quantity_to_next=min_transfer_quantity_to_next,
        )
        self.session.add(operation)
        self.session.commit()
        return operation

    def create_order(
        self,
        *,
        order_number: str,
        client_name: str,
        product_name: str,
        quantity: float,
        shipment_date: date,
        route_id: int,
        status: str = ORDER_STATUS_NEW,
    ) -> Order:
        """Create an order for manual MVP planning."""
        _require_text(order_number, "Номер заказа")
        _require_text(client_name, "Клиент")
        _require_text(product_name, "Продукция")
        if quantity <= 0:
            raise ValueError("Тираж должен быть больше 0.")
        route = self.session.get(Route, route_id)
        if route is None:
            raise ValueError("Маршрут не найден.")
        order = Order(
            order_number=order_number.strip(),
            client_name=client_name.strip(),
            product_name=product_name.strip(),
            quantity=quantity,
            shipment_date=shipment_date,
            route_id=route_id,
            status=status,
        )
        self.session.add(order)
        self.session.commit()
        return order

    def list_work_centers(self) -> list[WorkCenter]:
        """Return work centers ordered by name."""
        return list(self.session.scalars(select(WorkCenter).order_by(WorkCenter.name)).all())

    def list_routes(self) -> list[Route]:
        """Return routes with operations ordered by name."""
        return list(
            self.session.scalars(
                select(Route).options(selectinload(Route.operations).selectinload(RouteOperation.work_center)).order_by(Route.name)
            ).all()
        )


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"Поле «{field_name}» обязательно.")
