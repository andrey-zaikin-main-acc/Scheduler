"""Plotly Gantt chart component helpers."""

import plotly.express as px


def build_gantt_figure(rows: list[dict[str, object]], *, color_by: str):
    """Build a Plotly timeline figure from Gantt rows."""
    chart_rows = [
        {**row, "start_datetime": row.get("start_datetime", row.get("start")), "end_datetime": row.get("end_datetime", row.get("finish"))}
        for row in rows
    ]
    fig = px.timeline(
        chart_rows,
        x_start="start",
        x_end="finish",
        y="row",
        color=color_by,
        hover_data={
            "row": True,
            "task": True,
            "order": True,
            "work_center": True,
            "hours": True,
            "sequence_number": True,
            "start_datetime": True,
            "end_datetime": True,
            "start": False,
            "finish": False,
        },
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(
        xaxis_title="Дата и время",
        yaxis_title="",
        legend_title="Группировка",
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
    )
    return fig
