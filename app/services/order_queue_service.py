"""Pure construction of the immutable order sequence for a full recalculation."""

from dataclasses import dataclass
from enum import Enum
from numbers import Integral, Real
from typing import Iterable, Protocol

from app.constants import ORDER_STATUS_CANCELLED, ORDER_STATUS_NEW


class QueueKind(str, Enum):
    PLANNED = "previously_planned"
    NEW = "new"
    CONFLICTED = "previously_conflicted"
    CANCELLED = "cancelled"


class OrderLike(Protocol):
    id: int
    priority: object
    status: str | None
    child_group_key: str | None
    child_sequence_number: int | None
    is_linked_child_group: bool


@dataclass(frozen=True)
class QueueSnapshot:
    """Sequence fixed before planning; later results cannot reorder this pass."""

    order_ids: tuple[int, ...]
    kinds: tuple[QueueKind, ...]


def positive_integer(value: object) -> int | None:
    """Return a valid user priority, rejecting bool, zero and fractional values."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Integral):
        parsed = int(value)
    elif isinstance(value, Real) and float(value).is_integer():
        parsed = int(value)
    else:
        return None
    return parsed if parsed > 0 else None


def validate_priorities(orders: Iterable[OrderLike]) -> list[str]:
    """Validate priorities globally across every non-cancelled queue."""
    errors: list[str] = []
    owners: dict[int, int] = {}
    for order in orders:
        if order.status == ORDER_STATUS_CANCELLED:
            continue
        priority = positive_integer(order.priority)
        if priority is None:
            errors.append(f"Заказ ID {order.id}, поле «Приоритет»: требуется положительное целое число.")
            continue
        if priority in owners:
            errors.append(f"Заказ ID {order.id}, поле «Приоритет»: значение {priority} уже используется заказом ID {owners[priority]}.")
        else:
            owners[priority] = order.id
    return errors


def classify_order(order: OrderLike, planned_ids: set[int], conflict_ids: set[int]) -> QueueKind:
    if order.status == ORDER_STATUS_CANCELLED:
        return QueueKind.CANCELLED
    if order.status == ORDER_STATUS_NEW:
        return QueueKind.NEW
    if order.id in planned_ids:
        return QueueKind.PLANNED
    if order.id in conflict_ids:
        return QueueKind.CONFLICTED
    raise ValueError(f"Заказ ID {order.id}: пустой статус не имеет системного результата.")


def build_queue_snapshot(orders: Iterable[OrderLike], planned_ids: set[int], conflict_ids: set[int]) -> QueueSnapshot:
    """Build planned/new/conflicted queues, keeping linked groups contiguous."""
    classified = [(order, classify_order(order, planned_ids, conflict_ids)) for order in orders]
    # Form linked blocks before choosing a queue.  A system-created group is an
    # indivisible scheduling unit even when its members have different results
    # from the previous run.
    rank = {QueueKind.PLANNED: 0, QueueKind.NEW: 1, QueueKind.CONFLICTED: 2}
    grouped: dict[str, list[tuple[OrderLike, QueueKind]]] = {}
    blocks: list[tuple[QueueKind, int, int, list[OrderLike]]] = []
    for order, kind in classified:
        if kind == QueueKind.CANCELLED:
            continue
        if order.is_linked_child_group and order.child_group_key:
            grouped.setdefault(order.child_group_key, []).append((order, kind))
        else:
            blocks.append((kind, positive_integer(order.priority) or 10**30, order.id, [order]))
    for members_with_kind in grouped.values():
        kind = min((kind for _, kind in members_with_kind), key=rank.__getitem__)
        members = [order for order, _ in members_with_kind]
        members.sort(key=lambda item: (
            item.child_sequence_number if item.child_sequence_number is not None else 10**30,
            item.id,
        ))
        blocks.append((kind, min(positive_integer(item.priority) or 10**30 for item in members),
                       min(item.id for item in members), members))
    result: list[OrderLike] = []
    kinds: list[QueueKind] = []
    for kind in (QueueKind.PLANNED, QueueKind.NEW, QueueKind.CONFLICTED):
        for _, _, _, members in sorted((block for block in blocks if block[0] == kind),
                                       key=lambda block: (block[1], block[2])):
            result.extend(members)
            kinds.extend([kind] * len(members))
    return QueueSnapshot(tuple(order.id for order in result), tuple(kinds))
