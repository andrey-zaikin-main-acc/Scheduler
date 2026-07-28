from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.constants import ORDER_STATUS_NEW
from app.db.database import Base
from app.db.models import Order, Route, RouteOperation, WorkCenter
from app.services.draft_commit_service import DraftBundle, DraftCommitService


def make_session():
    engine=create_engine('sqlite:///:memory:'); Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def valid_row(route_id):
    return {'id':-1,'priority':1,'order_number':'D-1','client_name':'C','product_name':'P','quantity':10,
      'shipment_date':date(2026,8,1),'fixed_start_date':None,'route_id':route_id,'status':ORDER_STATUS_NEW,
      'planning_mode':'От даты отгрузки','child_group_key':None,'child_sequence_number':None,
      'is_child_order':False,'is_linked_child_group':False}


def seed(session):
    wc=WorkCenter(name='WC',available_hours_per_day=248); route=Route(name='R'); session.add_all([wc,route]); session.flush()
    session.add(RouteOperation(route_id=route.id,sequence_number=1,work_center_id=wc.id,labor_hours_per_1000=1)); session.commit(); return route


def test_invalid_draft_is_not_written_or_recalculated():
    s=make_session(); route=seed(s); calls=[]
    row=valid_row(route.id); row['client_name']=''
    result=DraftCommitService(s, lambda _: calls.append(1)).commit(DraftBundle(orders=[row]),sections={'orders'})
    assert not result.ok and s.query(Order).count()==0 and calls==[]


def test_valid_draft_has_one_outer_commit_and_recalculation():
    s=make_session(); route=seed(s); calls=[]
    class Recalc:
        def __init__(self, session): calls.append(session)
        def recalculate_plan(self):
            from app.services.recalculation_service import RecalculationService
            return RecalculationService(s, planning_start_date=date(2026,7,1)).recalculate_plan()
    result=DraftCommitService(s, Recalc).commit(DraftBundle(orders=[valid_row(route.id)]),sections={'orders'})
    assert result.ok and len(calls)==1 and s.query(Order).count()==1


def test_planner_exception_rolls_back_all_draft_mutations():
    s=make_session(); route=seed(s)
    class Broken:
        def __init__(self, _): pass
        def recalculate_plan(self): raise RuntimeError('boom')
    result=DraftCommitService(s, Broken).commit(DraftBundle(orders=[valid_row(route.id)]),sections={'orders'})
    assert not result.ok and s.query(Order).count()==0
