from types import SimpleNamespace

import pytest

from app.services.draft_history_service import DraftAction, DraftHistory
from app.services.order_queue_service import QueueKind, build_queue_snapshot, positive_integer, validate_priorities


def order(id, priority, status="Новый", group=None, sequence=None, linked=False):
    return SimpleNamespace(id=id, priority=priority, status=status, child_group_key=group,
                           child_sequence_number=sequence, is_linked_child_group=linked)


@pytest.mark.parametrize("value", [None, 0, -1, 1.5, "1", True])
def test_invalid_user_priorities(value):
    assert positive_integer(value) is None


@pytest.mark.parametrize("value", [1, 999999, 2.0])
def test_positive_integral_priorities(value):
    assert positive_integer(value) == int(value)


def test_duplicate_is_global_and_large_priorities_are_ordered():
    rows = [order(1, 100, ""), order(2, 100), order(3, 200, "")]
    assert "уже используется" in validate_priorities(rows)[0]
    snapshot = build_queue_snapshot(rows, {1}, {3})
    assert snapshot.order_ids == (1, 2, 3)
    assert snapshot.kinds == (QueueKind.PLANNED, QueueKind.NEW, QueueKind.CONFLICTED)


def test_linked_block_uses_minimum_priority_and_child_sequence():
    rows = [order(1, 10, group="g", sequence=2, linked=True),
            order(2, 2, group="g", sequence=1, linked=True), order(3, 3)]
    assert build_queue_snapshot(rows, set(), set()).order_ids == (2, 1, 3)


def test_empty_system_order_is_invalid():
    with pytest.raises(ValueError, match="системного результата"):
        build_queue_snapshot([order(1, 1, "")], set(), set())


def test_history_undo_redo_and_new_action_clears_redo():
    history = DraftHistory()
    first = DraftAction("orders", "batch-add", [], [{"ID": -1}, {"ID": -2}], rows=(-1, -2))
    history.record(first)
    assert history.undo() is first
    assert history.redo() is first
    history.undo()
    history.record(DraftAction("orders", "mass-delete", [1, 2], [], rows=(1, 2)))
    assert history.redo() is None


def test_clear_only_saved_section_actions():
    history = DraftHistory()
    history.record(DraftAction("routes", "cell", 1, 2, route_id=7))
    history.record(DraftAction("orders", "cell", 1, 2))
    history.clear_section("routes")
    assert [item.section for item in history.undo_stack] == ["orders"]
