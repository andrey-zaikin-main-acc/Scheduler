from datetime import date

from app.ui.components.gantt import build_gantt_figure


def test_gantt_figure_renders_single_day_operations_with_visible_width() -> None:
    fig = build_gantt_figure(
        [
            {
                "row": "EXCEL-104",
                "task": "1. Склейка",
                "start": date(2026, 6, 26),
                "finish": date(2026, 6, 26),
                "order": "EXCEL-104",
                "work_center": "Склейка",
                "hours": 155.22,
                "sequence_number": 1,
            }
        ],
        color_by="work_center",
    )

    assert fig.data[0].x[0] == 86_400_000
