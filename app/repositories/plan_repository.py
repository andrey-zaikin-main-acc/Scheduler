"""Repository helpers for planned operations."""

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import PlannedOperation, PlannedOperationDay


class PlanRepository:
    """Data access for the current saved production plan."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def clear_plan(self) -> None:
        """Remove the current saved plan."""
        self.session.execute(delete(PlannedOperationDay))
        self.session.execute(delete(PlannedOperation))
        self.session.flush()

    def list_planned_operations(self) -> Sequence[PlannedOperation]:
        """Return planned operations ordered by start date and order."""
        return self.session.scalars(
            select(PlannedOperation).order_by(
                PlannedOperation.planned_start_date,
                PlannedOperation.order_id,
                PlannedOperation.sequence_number,
            )
        ).all()

    def add_planned_operation(self, planned_operation: PlannedOperation) -> PlannedOperation:
        """Persist a planned operation aggregate."""
        self.session.add(planned_operation)
        self.session.flush()
        return planned_operation
