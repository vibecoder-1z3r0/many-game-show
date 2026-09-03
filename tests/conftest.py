"""Shared test fixtures — an isolated in-memory DB per test."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from manygameshow.database import get_session
from manygameshow.main import app


@pytest.fixture
def client() -> Generator[TestClient]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    def get_session_override() -> Generator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_session_override
    # Deliberately not using TestClient as a context manager: that would
    # trigger the app's lifespan, which calls create_db_and_tables() against
    # the real module-level engine (an actual manygameshow.db file on disk)
    # even though request handling itself is correctly isolated above.
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()
    engine.dispose()
