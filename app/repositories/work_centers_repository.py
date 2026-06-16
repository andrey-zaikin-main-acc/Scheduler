"""Repository helpers for production work centers."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import WorkCenter


class WorkCentersRepository:
    """Data access for work centers."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_work_centers(self) -> Sequence[WorkCenter]:
        """Return active and inactive work centers ordered by name."""
        return self.session.scalars(select(WorkCenter).order_by(WorkCenter.name)).all()

    def create_work_center(self, *, name: str, available_hours_per_day: float) -> WorkCenter:
        """Create a work center with positive daily capacity."""
        work_center = WorkCenter(name=name, available_hours_per_day=available_hours_per_day)
        self.session.add(work_center)
        self.session.flush()
        return work_center

    def update_work_center(
        self,
        work_center_id: int,
        *,
        name: str,
        available_hours_per_day: float,
        is_active: bool,
    ) -> WorkCenter | None:
        """Update a work center directory entry."""
        work_center = self.session.get(WorkCenter, work_center_id)
        if work_center is None:
            return None
        work_center.name = name
        work_center.available_hours_per_day = available_hours_per_day
        work_center.is_active = is_active
        self.session.flush()
        return work_center
