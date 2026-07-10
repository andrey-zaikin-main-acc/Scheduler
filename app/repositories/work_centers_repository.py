"""Repository helpers for production work centers."""

from collections.abc import Sequence
from datetime import time

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from app.db.models import (
    PlannedOperation,
    PlannedOperationDay,
    RouteOperation,
    WorkCenter,
)


class WorkCentersRepository:
    """Data access for work centers."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_work_centers(self) -> Sequence[WorkCenter]:
        """Return active and inactive work centers ordered by name."""
        return self.session.scalars(select(WorkCenter).order_by(WorkCenter.name)).all()

    def create_work_center(
        self,
        *,
        name: str,
        available_hours_per_day: float,
        workday_start_time: time = time(hour=9),
        is_active: bool = True,
        prevent_order_interruption: bool = False,
    ) -> WorkCenter:
        """Create a work center with positive daily capacity."""
        work_center = WorkCenter(
            name=name,
            available_hours_per_day=available_hours_per_day,
            workday_start_time=workday_start_time,
            is_active=is_active,
            prevent_order_interruption=prevent_order_interruption,
        )
        self.session.add(work_center)
        self.session.flush()
        return work_center

    def update_work_center(
        self,
        work_center_id: int,
        *,
        name: str,
        available_hours_per_day: float,
        workday_start_time: time,
        is_active: bool,
        prevent_order_interruption: bool,
    ) -> WorkCenter | None:
        """Update a work center directory entry."""
        work_center = self.session.get(WorkCenter, work_center_id)
        if work_center is None:
            return None
        work_center.name = name
        work_center.available_hours_per_day = available_hours_per_day
        work_center.workday_start_time = workday_start_time
        work_center.is_active = is_active
        work_center.prevent_order_interruption = prevent_order_interruption
        self.session.flush()
        return work_center

    def work_center_has_dependencies(self, work_center_id: int) -> bool:
        """Return whether a work center is referenced by routes or saved plan rows."""
        checks = (
            select(exists().where(RouteOperation.work_center_id == work_center_id)),
            select(exists().where(PlannedOperation.work_center_id == work_center_id)),
            select(
                exists().where(PlannedOperationDay.work_center_id == work_center_id)
            ),
        )
        return any(bool(self.session.scalar(statement)) for statement in checks)

    def delete_work_center(self, work_center_id: int) -> bool:
        """Delete a work center only when no route or plan rows reference it."""
        if self.work_center_has_dependencies(work_center_id):
            return False
        result = self.session.execute(
            delete(WorkCenter).where(WorkCenter.id == work_center_id)
        )
        self.session.flush()
        return bool(result.rowcount)
