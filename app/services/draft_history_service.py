"""Session-only undo/redo history for screen drafts (never database transactions)."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
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
