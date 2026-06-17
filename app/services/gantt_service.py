"""Prepare Gantt chart rows from persisted detailed planned operation placements."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import PlannedOperation, PlannedOperationDay


@dataclass(frozen=True)
class GanttRow:
    """One timeline bar for a Gantt chart."""

    row: str
    task: str
    start: datetime
    finish: datetime
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
            "start_datetime": self.start,
            "end_datetime": self.finish,
            "order": self.order,
            "work_center": self.work_center,
            "hours": round(self.hours, 2),
            "sequence_number": self.sequence_number,
        }


class GanttService:
    """Build Gantt rows in order and work-center modes from intraday placements."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_gantt_by_orders(self) -> list[dict[str, object]]:
        """Return Gantt rows where each lane is an order."""
        rows = []
        for day in self._load_planned_operation_days():
            operation = day.planned_operation
            rows.append(
                GanttRow(
                    row=operation.order.order_number if operation.order else f"Заказ {operation.order_id}",
                    task=_operation_task(operation),
                    start=_day_start(day),
                    finish=_day_finish(day),
                    order=operation.order.order_number if operation.order else str(operation.order_id),
                    work_center=day.work_center.name if day.work_center else str(day.work_center_id),
                    hours=day.hours,
                    sequence_number=operation.sequence_number,
                )
            )
        return [row.to_dict() for row in rows]

    def get_gantt_by_work_centers(self) -> list[dict[str, object]]:
        """Return Gantt rows where each lane is a work center."""
        rows = []
        for day in self._load_planned_operation_days():
            operation = day.planned_operation
            rows.append(
                GanttRow(
                    row=day.work_center.name if day.work_center else f"Участок {day.work_center_id}",
                    task=operation.order.order_number if operation.order else f"Заказ {operation.order_id}",
                    start=_day_start(day),
                    finish=_day_finish(day),
                    order=operation.order.order_number if operation.order else str(operation.order_id),
                    work_center=day.work_center.name if day.work_center else str(day.work_center_id),
                    hours=day.hours,
                    sequence_number=operation.sequence_number,
                )
            )
        return [row.to_dict() for row in rows]

    def _load_planned_operation_days(self) -> list[PlannedOperationDay]:
        """Load detailed planned placements with relations needed for Gantt labels."""
        return list(
            self.session.scalars(
                select(PlannedOperationDay)
                .join(PlannedOperationDay.planned_operation)
                .options(
                    selectinload(PlannedOperationDay.work_center),
                    selectinload(PlannedOperationDay.planned_operation).selectinload(PlannedOperation.order),
                    selectinload(PlannedOperationDay.planned_operation).selectinload(PlannedOperation.work_center),
                )
                .order_by(
                    PlannedOperationDay.start_datetime,
                    PlannedOperation.order_id,
                    PlannedOperation.sequence_number,
                    PlannedOperationDay.id,
                )
            ).all()
        )


def _operation_task(operation: PlannedOperation) -> str:
    work_center_name = operation.work_center.name if operation.work_center else f"Участок {operation.work_center_id}"
    return f"{operation.sequence_number}. {work_center_name}"


def _day_start(day: PlannedOperationDay) -> datetime:
    return day.start_datetime or datetime.combine(day.date, time(hour=9))


def _day_finish(day: PlannedOperationDay) -> datetime:
    return day.end_datetime or _day_start(day) + timedelta(hours=day.hours)
