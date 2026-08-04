"""Session-only undo/redo history for screen drafts (never database transactions)."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from copy import deepcopy
from uuid import uuid4


@dataclass(frozen=True)
class DraftAction:
    section: str
    action_type: str
    before: Any
    after: Any
    rows: tuple[object, ...] = ()
    fields: tuple[str, ...] = ()
    route_id: int | None = None
    focus: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DraftHistory:
    """Global linear action history with a redo branch."""

    def __init__(self) -> None:
        self.undo_stack: list[DraftAction] = []
        self.redo_stack: list[DraftAction] = []

    def record(self, action: DraftAction) -> None:
        self.undo_stack.append(action)
        self.redo_stack.clear()

    def undo(self) -> DraftAction | None:
        if not self.undo_stack:
            return None
        action = self.undo_stack.pop()
        self.redo_stack.append(action)
        return action

    def redo(self) -> DraftAction | None:
        if not self.redo_stack:
            return None
        action = self.redo_stack.pop()
        self.undo_stack.append(action)
        return action

    def clear_section(self, section: str, route_id: int | None = None) -> None:
        def keep(action: DraftAction) -> bool:
            return action.section != section or (route_id is not None and action.route_id != route_id)
        self.undo_stack = [action for action in self.undo_stack if keep(action)]
        self.redo_stack = [action for action in self.redo_stack if keep(action)]

    def clear(self) -> None:
        self.undo_stack.clear(); self.redo_stack.clear()


HISTORY_SESSION_KEY = "draft_history"


def session_history(state: Any) -> DraftHistory:
    """Return the one history shared by every editable screen in a session."""
    if HISTORY_SESSION_KEY not in state:
        state[HISTORY_SESSION_KEY] = DraftHistory()
    return state[HISTORY_SESSION_KEY]


def apply_action(state: Any, action: DraftAction, *, undo: bool) -> None:
    """Apply an action snapshot to its production draft in ``session_state``.

    ``focus`` may override the conventional key for per-route operation drafts
    and carries pending-delete snapshots for order deletion actions.
    """
    value = deepcopy(action.before if undo else action.after)
    key = action.focus.get("session_key") or {
        "orders": "orders_draft_rows",
        "routes": "routes_draft_rows",
        "operations": "route_operations_drafts_by_route_id",
        "work_centers": "work_centers_draft_rows",
    }.get(action.section)
    if key:
        if action.section == "operations" and action.route_id is not None and isinstance(value, list):
            drafts = state.setdefault(key, {})
            drafts[action.route_id] = value
        else:
            state[key] = value
    pending_key = action.focus.get("pending_delete_key")
    if pending_key:
        state[pending_key] = set(action.focus["pending_delete_before" if undo else "pending_delete_after"])
    state["draft_visual_event"] = {
        "animation": "restore" if undo and action.action_type == "delete" else ("remove" if action.action_type == "delete" else "cell-change"),
        "rows": action.rows,
        "fields": action.fields,
        "focus": action.focus,
    }


def undo_session(state: Any) -> DraftAction | None:
    action = session_history(state).undo()
    if action:
        apply_action(state, action, undo=True)
    return action


def redo_session(state: Any) -> DraftAction | None:
    action = session_history(state).redo()
    if action:
        apply_action(state, action, undo=False)
    return action
