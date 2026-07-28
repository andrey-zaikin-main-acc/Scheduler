"""SQLAlchemy models for the production planner MVP."""

from datetime import UTC, date, datetime, time
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.constants import PLANNING_MODE_SHIPMENT


def utc_now() -> datetime:
    """Return a timezone-naive UTC timestamp for SQLite storage."""
    return datetime.now(UTC).replace(tzinfo=None)


class Order(Base):
    """Customer order planned against a technological route."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    order_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    shipment_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    calculated_shipment_date: Mapped[Optional[date]] = mapped_column(Date)
    planning_mode: Mapped[str] = mapped_column(String(50), default=PLANNING_MODE_SHIPMENT, nullable=False, index=True)
    fixed_start_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    child_group_key: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    child_sequence_number: Mapped[Optional[int]] = mapped_column(Integer)
    is_child_order: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_linked_child_group: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), nullable=False, index=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    calculated_start_date: Mapped[Optional[date]] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    route: Mapped["Route"] = relationship(back_populates="orders")
    planned_operations: Mapped[list["PlannedOperation"]] = relationship(back_populates="order")
    conflicts: Mapped[list["PlanningConflict"]] = relationship(back_populates="order")

    __table_args__ = (CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),)


class WorkCenter(Base):
    """Production work center with a fixed daily capacity for MVP planning."""

    __tablename__ = "work_centers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    available_hours_per_day: Mapped[float] = mapped_column(Float, nullable=False)
    workday_start_time: Mapped[time] = mapped_column(
        Time, default=time(hour=9), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    prevent_order_interruption: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    route_operations: Mapped[list["RouteOperation"]] = relationship(back_populates="work_center")
    planned_operations: Mapped[list["PlannedOperation"]] = relationship(back_populates="work_center")
    planned_operation_days: Mapped[list["PlannedOperationDay"]] = relationship(back_populates="work_center")
    conflicts: Mapped[list["PlanningConflict"]] = relationship(back_populates="work_center")

    __table_args__ = (CheckConstraint("available_hours_per_day > 0", name="ck_work_centers_hours_positive"),)


class Route(Base):
    """Technological route consisting of ordered operations."""

    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    prevent_order_interruption: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    operations: Mapped[list["RouteOperation"]] = relationship(
        back_populates="route",
        order_by="RouteOperation.sequence_number",
    )
    orders: Mapped[list[Order]] = relationship(back_populates="route")


class RouteOperation(Base):
    """Ordered operation in a technological route."""

    __tablename__ = "route_operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    work_center_id: Mapped[int] = mapped_column(ForeignKey("work_centers.id"), nullable=False, index=True)
    labor_hours_per_1000: Mapped[float] = mapped_column(Float, nullable=False)
    min_transfer_quantity_to_next: Mapped[Optional[float]] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    route: Mapped[Route] = relationship(back_populates="operations")
    work_center: Mapped[WorkCenter] = relationship(back_populates="route_operations")
    planned_operations: Mapped[list["PlannedOperation"]] = relationship(back_populates="route_operation")

    __table_args__ = (
        UniqueConstraint("route_id", "sequence_number", name="uq_route_operations_route_sequence"),
        CheckConstraint("sequence_number > 0", name="ck_route_operations_sequence_positive"),
        CheckConstraint("labor_hours_per_1000 > 0", name="ck_route_operations_labor_positive"),
        CheckConstraint(
            "min_transfer_quantity_to_next IS NULL OR min_transfer_quantity_to_next > 0",
            name="ck_route_operations_transfer_positive",
        ),
    )


class PlannedOperation(Base):
    """Aggregated planned operation for an order and route operation."""

    __tablename__ = "planned_operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    route_operation_id: Mapped[int] = mapped_column(ForeignKey("route_operations.id"), nullable=False, index=True)
    work_center_id: Mapped[int] = mapped_column(ForeignKey("work_centers.id"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    required_hours: Mapped[float] = mapped_column(Float, nullable=False)
    planned_hours: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    order: Mapped[Order] = relationship(back_populates="planned_operations")
    route_operation: Mapped[RouteOperation] = relationship(back_populates="planned_operations")
    work_center: Mapped[WorkCenter] = relationship(back_populates="planned_operations")
    days: Mapped[list["PlannedOperationDay"]] = relationship(back_populates="planned_operation")

    __table_args__ = (
        CheckConstraint("sequence_number > 0", name="ck_planned_operations_sequence_positive"),
        CheckConstraint("required_hours > 0", name="ck_planned_operations_required_hours_positive"),
        CheckConstraint("planned_hours >= 0", name="ck_planned_operations_planned_hours_non_negative"),
        CheckConstraint("planned_start_date <= planned_end_date", name="ck_planned_operations_date_order"),
    )


class PlannedOperationDay(Base):
    """Daily placement of planned operation hours."""

    __tablename__ = "planned_operation_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    planned_operation_id: Mapped[int] = mapped_column(ForeignKey("planned_operations.id"), nullable=False, index=True)
    work_center_id: Mapped[int] = mapped_column(ForeignKey("work_centers.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hours: Mapped[float] = mapped_column(Float, nullable=False)
    start_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime)
    end_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime)
    quantity_part: Mapped[Optional[float]] = mapped_column(Float)

    planned_operation: Mapped[PlannedOperation] = relationship(back_populates="days")
    work_center: Mapped[WorkCenter] = relationship(back_populates="planned_operation_days")

    __table_args__ = (
        CheckConstraint("hours > 0", name="ck_planned_operation_days_hours_positive"),
        CheckConstraint("start_datetime < end_datetime", name="ck_planned_operation_days_datetime_order"),
        CheckConstraint("quantity_part IS NULL OR quantity_part >= 0", name="ck_planned_operation_days_quantity_non_negative"),
    )


class PlanningConflict(Base):
    """Conflict detected when an order cannot be planned in the allowed window."""

    __tablename__ = "planning_conflicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    shipment_date: Mapped[date] = mapped_column(Date, nullable=False)
    work_center_id: Mapped[Optional[int]] = mapped_column(ForeignKey("work_centers.id"), index=True)
    required_hours: Mapped[float] = mapped_column(Float, nullable=False)
    available_hours: Mapped[float] = mapped_column(Float, nullable=False)
    deficit_hours: Mapped[float] = mapped_column(Float, nullable=False)
    blocking_order_ids: Mapped[Optional[str]] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    order: Mapped[Order] = relationship(back_populates="conflicts")
    work_center: Mapped[Optional[WorkCenter]] = relationship(back_populates="conflicts")

    __table_args__ = (
        CheckConstraint("required_hours >= 0", name="ck_planning_conflicts_required_hours_non_negative"),
        CheckConstraint("available_hours >= 0", name="ck_planning_conflicts_available_hours_non_negative"),
        CheckConstraint("deficit_hours >= 0", name="ck_planning_conflicts_deficit_hours_non_negative"),
    )


class RecalculationRun(Base):
    """Single recalculation run summary."""

    __tablename__ = "recalculation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)

    changes: Mapped[list["PlanChange"]] = relationship(back_populates="recalculation_run")


class PlanChange(Base):
    """Difference between the previous saved plan and a recalculated plan."""

    __tablename__ = "plan_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recalculation_run_id: Mapped[int] = mapped_column(ForeignKey("recalculation_runs.id"), nullable=False, index=True)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"), index=True)
    planned_operation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("planned_operations.id"), index=True)
    operation_sequence_number: Mapped[Optional[int]] = mapped_column(Integer)
    change_type: Mapped[str] = mapped_column(String(100), nullable=False)
    old_start_date: Mapped[Optional[date]] = mapped_column(Date)
    old_end_date: Mapped[Optional[date]] = mapped_column(Date)
    new_start_date: Mapped[Optional[date]] = mapped_column(Date)
    new_end_date: Mapped[Optional[date]] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    recalculation_run: Mapped[RecalculationRun] = relationship(back_populates="changes")


class Setting(Base):
    """Key-value setting for local MVP configuration stored in SQLite."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
