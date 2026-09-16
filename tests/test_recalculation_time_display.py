from contextlib import nullcontext
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.ui.pages import common
from app.ui.pages.common import format_recalculation_time


LOCAL_UTC_PLUS_THREE = timezone(timedelta(hours=3))


def test_naive_utc_recalculation_time_is_displayed_in_local_timezone() -> None:
    stored_value = datetime(2026, 9, 16, 14, 16)

    displayed = format_recalculation_time(
        stored_value, local_timezone=LOCAL_UTC_PLUS_THREE
    )

    assert displayed == "16.09.2026 17:16"
    assert stored_value == datetime(2026, 9, 16, 14, 16)
    assert stored_value.tzinfo is None


def test_aware_utc_recalculation_time_is_converted_and_formatted() -> None:
    stored_value = datetime(2026, 9, 16, 14, 16, tzinfo=UTC)

    displayed = format_recalculation_time(
        stored_value, local_timezone=LOCAL_UTC_PLUS_THREE
    )

    assert displayed == "16.09.2026 17:16"
    assert stored_value == datetime(2026, 9, 16, 14, 16, tzinfo=UTC)


def test_aware_local_recalculation_time_does_not_receive_offset_twice() -> None:
    already_local = datetime(2026, 9, 16, 17, 16, tzinfo=LOCAL_UTC_PLUS_THREE)

    displayed = format_recalculation_time(
        already_local, local_timezone=LOCAL_UTC_PLUS_THREE
    )

    assert displayed == "16.09.2026 17:16"
    assert displayed.count(":") == 1


class _StatusHost:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def warning(self, message: str) -> None:
        self.messages.append(("warning", message))

    def success(self, message: str) -> None:
        self.messages.append(("success", message))

    def caption(self, message: str) -> None:
        self.messages.append(("caption", message))


def test_plan_freshness_comparison_stays_in_naive_utc() -> None:
    finished_at = datetime(2026, 9, 16, 14, 16)
    last_run = SimpleNamespace(finished_at=finished_at)
    session = Mock()
    session.scalars.return_value.first.return_value = last_run
    session.scalar.side_effect = [0, datetime(2026, 9, 16, 14, 17)]
    host = _StatusHost()

    with (
        patch.object(common, "SessionLocal", return_value=nullcontext(session)),
        patch.object(common.st, "session_state", {}),
        patch.object(
            common,
            "format_recalculation_time",
            return_value="16.09.2026 17:16",
        ) as formatter,
    ):
        common._render_plan_status(host)

    assert ("warning", "План: требует пересчёта") in host.messages
    assert ("caption", "Последний пересчёт: 16.09.2026 17:16") in host.messages
    formatter.assert_called_once_with(finished_at)
    assert last_run.finished_at is finished_at
    assert last_run.finished_at.tzinfo is None
