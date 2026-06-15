import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
from app.db.models import Order, Route, RouteOperation, Setting, WorkCenter
from app.db.seed_data import seed_demo_data


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return session_factory()


def test_seed_demo_data_is_idempotent() -> None:
    with make_session() as session:
        seed_demo_data(session)
        seed_demo_data(session)

        assert session.query(WorkCenter).count() == 4
        assert session.query(Route).count() == 1
        assert session.query(RouteOperation).count() == 4
        assert session.query(Order).count() == 4
        assert session.query(Setting).count() == 2


def test_seed_demo_route_contains_transfer_batches() -> None:
    with make_session() as session:
        seed_demo_data(session)

        route = session.scalar(select(Route).where(Route.name == "Маршрут A"))
        assert route is not None

        operations = session.scalars(
            select(RouteOperation)
            .where(RouteOperation.route_id == route.id)
            .order_by(RouteOperation.sequence_number)
        ).all()

        assert [operation.min_transfer_quantity_to_next for operation in operations] == [
            1000.0,
            1000.0,
            2000.0,
            None,
        ]
