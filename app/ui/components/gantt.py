"""Plotly Gantt chart component helpers."""

from datetime import date, timedelta

import plotly.express as px


def build_gantt_figure(rows: list[dict[str, object]], *, color_by: str):
    """Build a Plotly timeline figure from Gantt rows."""
    chart_rows = [_with_visual_finish(row) for row in rows]
    fig = px.timeline(
        chart_rows,
        x_start="start",
        x_end="_visual_finish",
        y="row",
        color=color_by,
        hover_data={
            "row": True,
            "task": True,
            "order": True,
            "work_center": True,
            "hours": True,
            "sequence_number": True,
            "start": True,
            "finish": True,
            "_visual_finish": False,
        },
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(
        xaxis_title="Дата",
        yaxis_title="",
        legend_title="Группировка",
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
    )
    return fig


def _with_visual_finish(row: dict[str, object]) -> dict[str, object]:
    """Return a chart row whose end date is exclusive for visible day-width bars."""
    chart_row = dict(row)
    finish = chart_row.get("finish")
    if isinstance(finish, date):
        chart_row["_visual_finish"] = finish + timedelta(days=1)
    else:
        chart_row["_visual_finish"] = finish
    return chart_row
