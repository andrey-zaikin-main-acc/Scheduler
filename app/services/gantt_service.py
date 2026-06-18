"""Prepare Gantt chart rows from persisted detailed planned operation placements."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import PlannedOperation, PlannedOperationDay

_CONTIGUOUS_TOLERANCE = timedelta(seconds=1)


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
    order_id: int
    work_center_id: int
    route_operation_id: int | None

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
                self._build_row(
                    day=day,
                    row=operation.order.order_number if operation.order else f"Заказ {operation.order_id}",
                    task=_operation_task(operation),
                )
            )
        return [row.to_dict() for row in self._merge_contiguous_rows(rows)]

    def get_gantt_by_work_centers(self) -> list[dict[str, object]]:
        """Return Gantt rows where each lane is a work center."""
        rows = []
        for day in self._load_planned_operation_days():
            operation = day.planned_operation
            rows.append(
                self._build_row(
                    day=day,
                    row=day.work_center.name if day.work_center else f"Участок {day.work_center_id}",
                    task=operation.order.order_number if operation.order else f"Заказ {operation.order_id}",
                )
            )
        return [row.to_dict() for row in self._merge_contiguous_rows(rows)]

    def _build_row(self, *, day: PlannedOperationDay, row: str, task: str) -> GanttRow:
        operation = day.planned_operation
        return GanttRow(
            row=row,
            task=task,
            start=_day_start(day),
            finish=_day_finish(day),
            order=operation.order.order_number if operation.order else str(operation.order_id),
            work_center=day.work_center.name if day.work_center else str(day.work_center_id),
            hours=day.hours,
            sequence_number=operation.sequence_number,
            order_id=operation.order_id,
            work_center_id=day.work_center_id,
            route_operation_id=operation.route_operation_id,
        )

    def _merge_contiguous_rows(self, rows: list[GanttRow]) -> list[GanttRow]:
        """Merge adjacent pieces of the same operation with no real time gap."""
        merged: list[GanttRow] = []
        for row in sorted(rows, key=_merge_sort_key):
            previous = merged[-1] if merged else None
            if previous and _can_merge(previous, row):
                merged[-1] = GanttRow(
                    row=previous.row,
                    task=previous.task,
                    start=min(previous.start, row.start),
                    finish=max(previous.finish, row.finish),
                    order=previous.order,
                    work_center=previous.work_center,
                    hours=previous.hours + row.hours,
                    sequence_number=previous.sequence_number,
                    order_id=previous.order_id,
                    work_center_id=previous.work_center_id,
                    route_operation_id=previous.route_operation_id,
                )
            else:
                merged.append(row)
        return sorted(merged, key=lambda row: (row.start, row.order_id, row.sequence_number, row.work_center_id))

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


def _merge_sort_key(row: GanttRow) -> tuple[int, int, int, int, datetime, datetime]:
    route_operation_id = row.route_operation_id or 0
    return (row.order_id, row.work_center_id, route_operation_id, row.sequence_number, row.start, row.finish)


def _can_merge(previous: GanttRow, current: GanttRow) -> bool:
    same_operation = (
        previous.order_id == current.order_id
        and previous.work_center_id == current.work_center_id
        and previous.sequence_number == current.sequence_number
        and previous.route_operation_id == current.route_operation_id
    )
    if not same_operation:
        return False
    gap = current.start - previous.finish
    return timedelta(0) <= gap <= _CONTIGUOUS_TOLERANCE
