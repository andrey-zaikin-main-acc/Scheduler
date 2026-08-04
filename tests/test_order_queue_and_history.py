from types import SimpleNamespace

import pytest

from app.services.draft_history import DraftAction, DraftHistory
from app.services.order_queue import build_queue_snapshot, positive_integer, validate_priorities


def order(id, priority, status="Новый", *, group=None, sequence=None, linked=False):
    return SimpleNamespace(id=id, priority=priority, status=status, child_group_key=group,
                           child_sequence_number=sequence, is_linked_child_group=linked)


@pytest.mark.parametrize("value", [None, "", 0, -1, 1.5, True])
def test_priority_must_be_positive_integer(value):
    assert positive_integer(value) is None


def test_priorities_are_global_and_large_values_are_valid():
    rows = [order(1, 1000), order(2, 1000)]
    assert "уже задано" in validate_priorities(rows)[0]
    assert positive_integer(10**12) == 10**12


def test_three_queues_and_linked_block_are_snapshotted():
    rows = [order(1, 3, "",), order(2, 2, group="g", sequence=2, linked=True),
            order(3, 10, group="g", sequence=1, linked=True), order(4, 1, "")]
    snapshot = build_queue_snapshot(rows, {1}, {4})
    assert snapshot.order_ids == (1, 3, 2, 4)
    rows[0].status = "Отменён"
    assert snapshot.order_ids == (1, 3, 2, 4)


def test_empty_system_order_is_invalid():
    with pytest.raises(ValueError, match="без системного результата"):
        build_queue_snapshot([order(1, 1, "")], set(), set())


def test_history_undo_redo_group_action_and_redo_branch():
    history = DraftHistory()
    batch = DraftAction("orders", "add_batch", [], [{"id": -1}, {"id": -2}], rows=(-1, -2))
    history.record(batch)
    assert history.undo() is batch
    assert history.redo() is batch
    assert history.undo() is batch
    history.record(DraftAction("orders", "delete_many", [{"id": 1}, {"id": 2}], [], rows=(1, 2)))
    assert not history.can_redo


def test_history_clear_only_saved_section():
    history = DraftHistory()
    history.record(DraftAction("orders", "cell", 1, 2))
    history.record(DraftAction("routes", "cell", 1, 2, route_id=7))
    history.clear_section("routes")
    assert history.undo().section == "orders"
