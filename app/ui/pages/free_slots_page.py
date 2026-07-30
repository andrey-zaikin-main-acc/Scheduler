"""Free slots page."""

from datetime import date, timedelta

import streamlit as st

from app.config import DEFAULT_FREE_SLOT_DAYS
from app.db.database import SessionLocal
from app.db.models import Route
from app.services.free_slots_service import FreeSlotsService
from app.ui.pages.page_utils import normalize_date_range
from sqlalchemy import select


def render_free_slots_page() -> None:
    """Render free work-center hours and approximate route capacity."""
    st.header("Свободные слоты")
    default_start = date.today()
    default_end = default_start + timedelta(days=DEFAULT_FREE_SLOT_DAYS - 1)

    period = st.date_input("Период", value=(default_start, default_end))
    start_date, end_date = normalize_date_range(period, default_start, default_end)

    with SessionLocal() as session:
        service = FreeSlotsService(session)
        free_slots = service.get_free_slots(start_date=start_date, end_date=end_date)
        route_capacities = service.get_route_capacities(
            start_date=start_date, end_date=end_date
        )

        routes = list(session.scalars(select(Route).where(Route.is_active.is_(True)).order_by(Route.name)).all())
        if routes:
            st.subheader("Проверка дат заказа")
            route_name = st.selectbox("Маршрут", [route.name for route in routes], key="free_slots_route")
            quantity = st.number_input("Тираж", min_value=0.01, value=1000.0, key="free_slots_quantity")
            route_id = next(route.id for route in routes if route.name == route_name)
            start_button, shipment_button = st.columns(2)
            if start_button.button("Показать свободные слоты запуска"):
                st.session_state["free_slots_search_result"] = service.find_start_slots(
                    route_id=route_id, quantity=quantity, start_date=start_date, end_date=end_date)
            if shipment_button.button("Показать свободные слоты отгрузки"):
                st.session_state["free_slots_search_result"] = service.find_shipment_slots(
                    route_id=route_id, quantity=quantity, start_date=start_date, end_date=end_date)
            if result := st.session_state.get("free_slots_search_result"):
                st.dataframe(result, use_container_width=True, hide_index=True)

    st.subheader("Свободные часы по участкам")
    if free_slots:
        st.dataframe(free_slots, use_container_width=True, hide_index=True)
    else:
        st.info("Нет данных по свободным слотам за выбранный период.")

    st.subheader("Теоретический максимальный тираж по маршрутам")
    st.caption(
        "Показатель основан только на суммарной свободной мощности участков и "
        "не учитывает последовательность операций, минимальные партии и срок "
        "отгрузки. Реально размещаемый тираж проверяйте в реестре заказов."
    )
    if route_capacities:
        st.dataframe(route_capacities, use_container_width=True, hide_index=True)
    else:
        st.info("Нет активных маршрутов для расчёта возможного тиража.")
