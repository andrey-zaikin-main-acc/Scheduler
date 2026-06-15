"""Repository helpers for planning conflicts."""

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import PlanningConflict


class ConflictsRepository:
    """Data access for planning conflicts."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def clear_conflicts(self) -> None:
        """Remove saved planning conflicts."""
        self.session.execute(delete(PlanningConflict))
        self.session.flush()

    def list_conflicts(self) -> Sequence[PlanningConflict]:
        """Return conflicts ordered by creation order."""
        return self.session.scalars(select(PlanningConflict).order_by(PlanningConflict.id)).all()

    def add_conflict(self, conflict: PlanningConflict) -> PlanningConflict:
        """Persist a planning conflict."""
        self.session.add(conflict)
        self.session.flush()
        return conflict
