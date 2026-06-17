from datetime import datetime

from app.ui.components.gantt import build_gantt_figure


def test_gantt_figure_uses_real_intraday_width() -> None:
    fig = build_gantt_figure(
        [
            {
                "row": "EXCEL-104",
                "task": "1. Склейка",
                "start": datetime(2026, 6, 26, 10),
                "finish": datetime(2026, 6, 26, 14),
                "start_datetime": datetime(2026, 6, 26, 10),
                "end_datetime": datetime(2026, 6, 26, 14),
                "order": "EXCEL-104",
                "work_center": "Склейка",
                "hours": 4,
                "sequence_number": 1,
            }
        ],
        color_by="work_center",
    )

    assert fig.data[0].x[0] == 14_400_000
