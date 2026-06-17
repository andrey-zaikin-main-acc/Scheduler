"""Repository helpers for technological routes."""

from collections.abc import Sequence

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Order, PlannedOperation, Route, RouteOperation


class RoutesRepository:
    """Data access for routes and their operations."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_routes(self) -> Sequence[Route]:
        """Return routes ordered by name."""
        return self.session.scalars(select(Route).order_by(Route.name)).all()

    def list_routes_with_operations(self) -> Sequence[Route]:
        """Return routes ordered by name with operations and work centers loaded."""
        return self.session.scalars(
            select(Route)
            .options(
                selectinload(Route.operations).selectinload(RouteOperation.work_center)
            )
            .order_by(Route.name)
        ).all()

    def get_route_with_operations(self, route_id: int) -> Route | None:
        """Return a route with ordered operations preloaded."""
        return self.session.scalar(
            select(Route)
            .where(Route.id == route_id)
            .options(
                selectinload(Route.operations).selectinload(RouteOperation.work_center)
            )
        )

    def create_route(
        self, *, name: str, description: str | None = None, is_active: bool = True
    ) -> Route:
        """Create a technological route."""
        route = Route(name=name, description=description, is_active=is_active)
        self.session.add(route)
        self.session.flush()
        return route

    def add_operation(
        self,
        *,
        route_id: int,
        sequence_number: int,
        work_center_id: int,
        labor_hours_per_1000: float,
        min_transfer_quantity_to_next: float | None = None,
    ) -> RouteOperation:
        """Append or insert a route operation."""
        operation = RouteOperation(
            route_id=route_id,
            sequence_number=sequence_number,
            work_center_id=work_center_id,
            labor_hours_per_1000=labor_hours_per_1000,
            min_transfer_quantity_to_next=min_transfer_quantity_to_next,
        )
        self.session.add(operation)
        self.session.flush()
        return operation

    def update_route(
        self, route_id: int, *, name: str, description: str | None, is_active: bool
    ) -> Route | None:
        """Update a technological route."""
        route = self.session.get(Route, route_id)
        if route is None:
            return None
        route.name = name
        route.description = description
        route.is_active = is_active
        self.session.flush()
        return route

    def update_operation(
        self,
        operation_id: int,
        *,
        sequence_number: int,
        work_center_id: int,
        labor_hours_per_1000: float,
        min_transfer_quantity_to_next: float | None = None,
    ) -> RouteOperation | None:
        """Update a route operation."""
        operation = self.session.get(RouteOperation, operation_id)
        if operation is None:
            return None
        operation.sequence_number = sequence_number
        operation.work_center_id = work_center_id
        operation.labor_hours_per_1000 = labor_hours_per_1000
        operation.min_transfer_quantity_to_next = min_transfer_quantity_to_next
        self.session.flush()
        return operation

    def delete_operation(self, operation_id: int) -> None:
        """Delete a route operation."""
        self.session.execute(
            delete(RouteOperation).where(RouteOperation.id == operation_id)
        )
        self.session.flush()

    def route_has_orders(self, route_id: int) -> bool:
        """Return whether a route is referenced by orders."""
        return bool(
            self.session.scalar(select(exists().where(Order.route_id == route_id)))
        )

    def delete_route(self, route_id: int) -> bool:
        """Delete a route only when no orders reference it."""
        if self.route_has_orders(route_id):
            return False
        self.session.execute(
            delete(RouteOperation).where(RouteOperation.route_id == route_id)
        )
        result = self.session.execute(delete(Route).where(Route.id == route_id))
        self.session.flush()
        return bool(result.rowcount)

    def operation_has_plan(self, operation_id: int) -> bool:
        """Return whether a route operation is referenced by saved plan rows."""
        return bool(
            self.session.scalar(
                select(
                    exists().where(PlannedOperation.route_operation_id == operation_id)
                )
            )
        )

    def delete_operation_safe(self, operation_id: int) -> bool:
        """Delete an operation only when no saved plan rows reference it."""
        if self.operation_has_plan(operation_id):
            return False
        result = self.session.execute(
            delete(RouteOperation).where(RouteOperation.id == operation_id)
        )
        self.session.flush()
        return bool(result.rowcount)
