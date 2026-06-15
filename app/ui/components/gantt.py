"""Plotly Gantt chart component helpers."""

import plotly.express as px


def build_gantt_figure(rows: list[dict[str, object]], *, color_by: str):
    """Build a Plotly timeline figure from Gantt rows."""
    fig = px.timeline(
        rows,
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
            "start": True,
            "finish": True,
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
