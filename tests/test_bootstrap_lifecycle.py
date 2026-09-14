from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from app.db import database
from app.services import bootstrap_service


def test_process_bootstrap_runs_schema_initialization_once_across_100_reruns(monkeypatch):
    calls = []
    monkeypatch.setattr(bootstrap_service, "_initialized_engine", None)
    monkeypatch.setattr(bootstrap_service, "initialize_database", lambda: calls.append("schema"))

    for _ in range(100):
        bootstrap_service.initialize_database_once()

    assert calls == ["schema"]


def test_failed_process_bootstrap_can_be_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(bootstrap_service, "_initialized_engine", None)

    def initialize():
        calls.append("schema")
        if len(calls) == 1:
            raise RuntimeError("temporary startup failure")

    monkeypatch.setattr(bootstrap_service, "initialize_database", initialize)
    try:
        bootstrap_service.initialize_database_once()
    except RuntimeError:
        pass
    bootstrap_service.initialize_database_once()

    assert calls == ["schema", "schema"]


def test_100_startup_checks_return_every_queue_pool_connection(monkeypatch, tmp_path):
    test_engine = create_engine(f"sqlite:///{tmp_path / 'stress.sqlite3'}")
    assert isinstance(test_engine.pool, QueuePool)
    calls = 0
    real_initialize = bootstrap_service.initialize_database

    def initialize():
        nonlocal calls
        calls += 1
        real_initialize()

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(bootstrap_service, "_initialized_engine", None)
    monkeypatch.setattr(bootstrap_service, "initialize_database", initialize)
    before = test_engine.pool.checkedout()

    for _ in range(100):
        bootstrap_service.initialize_database_once()

    assert calls == 1
    assert test_engine.pool.checkedout() == before == 0
