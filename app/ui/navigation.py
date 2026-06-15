"""Navigation shell for the MVP user interface."""

import streamlit as st


def render_navigation() -> None:
    """Render placeholder navigation for the planned MVP screens."""
    st.title("Production Planner MVP")
    st.caption("Локальный прототип планирования производства с SQLite")

    page = st.sidebar.radio(
        "Раздел",
        [
            "Реестр заказов",
            "Маршруты",
            "Участки",
            "Производственный план",
            "Диаграмма Ганта",
            "Свободные слоты",
            "Конфликты",
            "Результаты пересчёта",
        ],
    )

    st.info(f"Раздел «{page}» будет реализован в следующих итерациях.")
    st.markdown(
        """
        **Следующий технический фокус:** модель данных SQLite и чистый planning engine,
        покрытый unit-тестами до наполнения экранов бизнес-логикой.
        """
    )
