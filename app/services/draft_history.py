"""Session-only undo/redo history for screen-draft actions."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class DraftAction:
    section: str
    action_type: str
    before: Any
    after: Any
    rows: tuple[str | int, ...] = ()
    fields: tuple[str, ...] = ()
    route_id: int | None = None
    focus: dict[str, Any] = field(default_factory=dict)
    action_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class DraftHistory:
    """Global linear action history, independent from database transactions."""

    def __init__(self) -> None:
        self._undo: list[DraftAction] = []
        self._redo: list[DraftAction] = []

    def record(self, action: DraftAction) -> None:
        self._undo.append(action)
        self._redo.clear()

    def undo(self) -> DraftAction | None:
        if not self._undo:
            return None
        action = self._undo.pop()
        self._redo.append(action)
        return action

    def redo(self) -> DraftAction | None:
        if not self._redo:
            return None
        action = self._redo.pop()
        self._undo.append(action)
        return action

    def clear_section(self, section: str, route_id: int | None = None) -> None:
        def keep(action: DraftAction) -> bool:
            return action.section != section or (route_id is not None and action.route_id != route_id)
        self._undo = [action for action in self._undo if keep(action)]
        self._redo = [action for action in self._redo if keep(action)]

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)
