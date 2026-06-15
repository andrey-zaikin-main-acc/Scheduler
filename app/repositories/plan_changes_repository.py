"""Repository helpers for plan changes created by recalculation."""

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import PlanChange


class PlanChangesRepository:
    """Data access for recalculation plan changes."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def clear_changes_for_run(self, recalculation_run_id: int) -> None:
        """Remove changes for one recalculation run."""
        self.session.execute(delete(PlanChange).where(PlanChange.recalculation_run_id == recalculation_run_id))
        self.session.flush()

    def add_changes(self, changes: list[PlanChange]) -> list[PlanChange]:
        """Persist a batch of plan changes."""
        self.session.add_all(changes)
        self.session.flush()
        return changes

    def list_changes_for_run(self, recalculation_run_id: int) -> Sequence[PlanChange]:
        """Return changes for one recalculation run."""
        return self.session.scalars(
            select(PlanChange)
            .where(PlanChange.recalculation_run_id == recalculation_run_id)
            .order_by(PlanChange.id)
        ).all()

    def list_latest_changes(self) -> Sequence[PlanChange]:
        """Return changes for the latest recalculation run that has changes."""
        latest_run_id = self.session.scalar(select(PlanChange.recalculation_run_id).order_by(PlanChange.recalculation_run_id.desc()))
        if latest_run_id is None:
            return []
        return self.list_changes_for_run(latest_run_id)
