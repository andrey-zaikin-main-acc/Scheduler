"""Pure order classification and immutable full-recalculation queue building."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable


class OrderQueue(str, Enum):
    PLANNED = "planned"
    NEW = "new"
    CONFLICTED = "conflicted"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class QueueSnapshot:
    """Order ids in the sequence fixed before the planning pass starts."""

    order_ids: tuple[int, ...]


def positive_integer(value: Any) -> int | None:
    """Return a user priority only when it is a positive integer."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not numeric.is_integer() or numeric <= 0:
        return None
    return int(numeric)


def classify_order(order: Any, planned_ids: set[int], conflict_ids: set[int]) -> OrderQueue:
    if order.status == "Отменён":
        return OrderQueue.CANCELLED
    if order.status == "Новый":
        return OrderQueue.NEW
    if order.id in planned_ids:
        return OrderQueue.PLANNED
    if order.id in conflict_ids:
        return OrderQueue.CONFLICTED
    raise ValueError(f"Заказ ID {order.id}: пустой статус без системного результата.")


def validate_priorities(orders: Iterable[Any]) -> list[str]:
    """Validate priorities globally across every non-cancelled queue."""
    errors: list[str] = []
    owners: dict[int, int] = {}
    for order in orders:
        if order.status == "Отменён":
            continue
        priority = positive_integer(order.priority)
        if priority is None:
            errors.append(f"Заказ ID {order.id}, поле «Приоритет»: требуется положительное целое число.")
        elif priority in owners:
            errors.append(f"Заказ ID {order.id}, поле «Приоритет»: значение {priority} уже задано заказу ID {owners[priority]}.")
        else:
            owners[priority] = order.id
    return errors


def build_queue_snapshot(orders: Iterable[Any], planned_ids: set[int], conflict_ids: set[int]) -> QueueSnapshot:
    """Build the three queues, keeping linked children as one stable block."""
    buckets = {queue: [] for queue in (OrderQueue.PLANNED, OrderQueue.NEW, OrderQueue.CONFLICTED)}
    for order in orders:
        queue = classify_order(order, planned_ids, conflict_ids)
        if queue != OrderQueue.CANCELLED:
            buckets[queue].append(order)

    result: list[int] = []
    for queue in (OrderQueue.PLANNED, OrderQueue.NEW, OrderQueue.CONFLICTED):
        rows = buckets[queue]
        groups: dict[str, list[Any]] = {}
        singles: list[Any] = []
        for row in rows:
            key = row.child_group_key if row.is_linked_child_group and row.child_group_key else None
            (groups.setdefault(key, []) if key else singles).append(row)
        blocks: list[tuple[int, list[Any]]] = [
            (min(positive_integer(row.priority) or 10**18 for row in members),
             sorted(members, key=lambda row: (row.child_sequence_number or 10**18, row.id)))
            for members in groups.values()
        ]
        blocks.extend((positive_integer(row.priority) or 10**18, [row]) for row in singles)
        blocks.sort(key=lambda item: (item[0], min(row.id for row in item[1])))
        result.extend(row.id for _, block in blocks for row in block)
    return QueueSnapshot(tuple(result))
