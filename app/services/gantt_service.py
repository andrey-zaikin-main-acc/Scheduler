"""Prepare Gantt chart rows from persisted planned operations."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import PlannedOperation


@dataclass(frozen=True)
class GanttRow:
    """One timeline bar for a Gantt chart."""

    row: str
    task: str
    start: date
    finish: date
    order: str
    work_center: str
    hours: float
    sequence_number: int

    def to_dict(self) -> dict[str, object]:
        """Return a Plotly/Streamlit friendly dict."""
        return {
            "row": self.row,
            "task": self.task,
            "start": self.start,
            "finish": self.finish,
            "order": self.order,
            "work_center": self.work_center,
            "hours": round(self.hours, 2),
            "sequence_number": self.sequence_number,
        }


class GanttService:
    """Build Gantt rows in order and work-center modes."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_gantt_by_orders(self) -> list[dict[str, object]]:
        """Return Gantt rows where each lane is an order."""
        rows = [
            GanttRow(
                row=operation.order.order_number if operation.order else f"Заказ {operation.order_id}",
                task=_operation_task(operation),
                start=operation.planned_start_date,
                finish=operation.planned_end_date,
                order=operation.order.order_number if operation.order else str(operation.order_id),
                work_center=operation.work_center.name if operation.work_center else str(operation.work_center_id),
                hours=operation.planned_hours,
                sequence_number=operation.sequence_number,
            )
            for operation in self._load_planned_operations()
        ]
        return [row.to_dict() for row in rows]

    def get_gantt_by_work_centers(self) -> list[dict[str, object]]:
        """Return Gantt rows where each lane is a work center."""
        rows = [
            GanttRow(
                row=operation.work_center.name if operation.work_center else f"Участок {operation.work_center_id}",
                task=operation.order.order_number if operation.order else f"Заказ {operation.order_id}",
                start=operation.planned_start_date,
                finish=operation.planned_end_date,
                order=operation.order.order_number if operation.order else str(operation.order_id),
                work_center=operation.work_center.name if operation.work_center else str(operation.work_center_id),
                hours=operation.planned_hours,
                sequence_number=operation.sequence_number,
            )
            for operation in self._load_planned_operations()
        ]
        return [row.to_dict() for row in rows]

    def _load_planned_operations(self) -> list[PlannedOperation]:
        """Load planned operations with relations needed for Gantt labels."""
        return list(
            self.session.scalars(
                select(PlannedOperation)
                .options(
                    selectinload(PlannedOperation.order),
                    selectinload(PlannedOperation.work_center),
                )
                .order_by(
                    PlannedOperation.planned_start_date,
                    PlannedOperation.order_id,
                    PlannedOperation.sequence_number,
                )
            ).all()
        )


def _operation_task(operation: PlannedOperation) -> str:
    work_center_name = operation.work_center.name if operation.work_center else f"Участок {operation.work_center_id}"
    return f"{operation.sequence_number}. {work_center_name}"
