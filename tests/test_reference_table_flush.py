from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Route, RouteOperation, WorkCenter
from app.services.draft_commit_service import DraftBundle, DraftCommitService
from app.services.draft_history_service import session_history
from app.ui.components.reference_table import (
    apply_reference_payload, reference_save_ready, request_reference_save,
)


def _event(revision, key, field, before, after):
    return {"client_revision": revision, "row_key": key, "field": field,
            "before": before, "after": after, "action_type": "cell"}


def test_active_route_flush_is_authoritative_and_is_persisted_to_sqlite():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        route = Route(name="Before", description="", is_active=True)
        db.add(route); db.commit()
        state = {"routes_draft_rows": [
            {"ID": route.id, "Название": "Before", "Описание": "", "Активен": True, "Операций": 0}
        ]}
        token = request_reference_save(state, section="routes", editor_keys=["routes_page_route_editor"])
        payload = {"client_revision": 1,
                   "events": [_event(1, route.id, "Название", "Before", "Active value")],
                   "flush_ack": token,
                   "snapshot": [{"ID": route.id, "Название": "Active value", "Описание": "",
                                 "Активен": True, "Операций": 0}]}
        rows = apply_reference_payload(
            state, payload, rows_key="routes_draft_rows", editor_key="routes_page_route_editor",
            section="routes", numeric_fields={"ID", "Операций"}, boolean_fields={"Активен"},
        )
        assert reference_save_ready(state, "routes")
        assert len(session_history(state).undo_stack) == 1
        result = DraftCommitService(db).save_reference_section(DraftBundle(routes=rows), "routes")
        assert result.ok
        assert db.get(Route, route.id).name == "Active value"


def test_route_save_waits_for_both_route_and_operation_snapshots_and_persists_operation():
    state = {}
    token = request_reference_save(state, section="routes", editor_keys=["route", "operation"])
    state["route_component_flush_ack"] = token
    assert not reference_save_ready(state, "routes")
    state["operation_component_flush_ack"] = token
    assert reference_save_ready(state, "routes")

    engine = create_engine("sqlite:///:memory:"); Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        wc = WorkCenter(name="WC", available_hours_per_day=160)
        route = Route(name="R", is_active=True)
        db.add_all([wc, route]); db.flush()
        operation = RouteOperation(route_id=route.id, sequence_number=1, work_center_id=wc.id,
                                   labor_hours_per_1000=1, min_transfer_quantity_to_next=None, is_active=True)
        db.add(operation); db.commit()
        bundle = DraftBundle(
            routes=[{"ID": route.id, "Название": "R", "Описание": "", "Активен": True, "Операций": 1}],
            operations=[{"ID": operation.id, "_route_id": route.id, "№": 1, "Участок": "WC",
                         "Трудоёмкость на 1000": 7.5, "Мин. передаточная партия": 0, "Активна": True}],
        )
        assert DraftCommitService(db).save_reference_section(bundle, "routes").ok
        assert db.get(RouteOperation, operation.id).labor_hours_per_1000 == 7.5


def test_invalid_active_work_center_snapshot_stays_dirty_and_is_not_written():
    engine = create_engine("sqlite:///:memory:"); Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        wc = WorkCenter(name="WC", available_hours_per_day=160)
        db.add(wc); db.commit()
        state = {"work_centers_draft_rows": [{"ID": wc.id, "Название": "WC",
            "Доступное время в месяц": 160, "Время начала рабочего дня": "09:00",
            "Активен": True, "Нельзя прерывать заказ при планировании": False}]}
        token = request_reference_save(state, section="work_centers", editor_keys=["wc"])
        rows = apply_reference_payload(state, {"client_revision": 1,
            "events": [_event(1, wc.id, "Доступное время в месяц", 160, -5)],
            "flush_ack": token, "snapshot": [{**state["work_centers_draft_rows"][0],
                                                "Доступное время в месяц": -5}]},
            rows_key="work_centers_draft_rows", editor_key="wc", section="work_centers",
            numeric_fields={"ID", "Доступное время в месяц"},
            boolean_fields={"Активен", "Нельзя прерывать заказ при планировании"})
        result = DraftCommitService(db).save_reference_section(DraftBundle(work_centers=rows), "work_centers")
        assert not result.ok
        assert state["work_centers_dirty"] is True
        assert state["work_centers_draft_rows"][0]["Доступное время в месяц"] == -5
        assert db.get(WorkCenter, wc.id).available_hours_per_day == 160
        assert len(session_history(state).undo_stack) == 1


def test_active_and_blurred_work_center_edits_persist_the_same_sqlite_value():
    for flush_ack in (None, "save-active"):
        engine = create_engine("sqlite:///:memory:"); Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        with Session() as db:
            wc = WorkCenter(name="WC", available_hours_per_day=160)
            db.add(wc); db.commit()
            original = {"ID": wc.id, "Название": "WC", "Доступное время в месяц": 160,
                        "Время начала рабочего дня": "09:00", "Активен": True,
                        "Нельзя прерывать заказ при планировании": False}
            state = {"work_centers_draft_rows": [original]}
            payload = {"client_revision": 1,
                       "events": [_event(1, wc.id, "Доступное время в месяц", 160, 200)]}
            if flush_ack:
                payload.update(flush_ack=flush_ack,
                               snapshot=[{**original, "Доступное время в месяц": 200}])
            rows = apply_reference_payload(
                state, payload, rows_key="work_centers_draft_rows", editor_key="wc",
                section="work_centers", numeric_fields={"ID", "Доступное время в месяц"},
                boolean_fields={"Активен", "Нельзя прерывать заказ при планировании"})
            assert DraftCommitService(db).save_reference_section(
                DraftBundle(work_centers=rows), "work_centers"
            ).ok
            assert db.get(WorkCenter, wc.id).available_hours_per_day == 200
