"""Shared pytest fixtures for the FastAPI app tests.

The suite runs against a real Postgres (per the project's Postgres-everywhere
choice). Point it at one with ``CLAZZZIKS_TEST_DATABASE_URL``; the default matches
the ``clazzziks_test`` database from the repo's ``docker-compose.yml``:

    docker compose up -d db
    uv run pytest

Each test gets empty, isolated tables (truncated between tests).
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from clazzziks import db
from clazzziks.api import create_app

TEST_DATABASE_URL = os.environ.get(
    "CLAZZZIKS_TEST_DATABASE_URL",
    "postgresql+psycopg://clazzziks:clazzziks@localhost:5432/clazzziks_test",
)


def _ensure_test_database() -> None:
    """Create the test database if it doesn't exist yet (best-effort)."""
    url = make_url(TEST_DATABASE_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": url.database},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    _ensure_test_database()
    engine = create_engine(TEST_DATABASE_URL, future=True)
    db.Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    """Fresh, isolated tables per test, with the admin seed re-applied lazily.

    Truncating with a throwaway engine (then clearing the module's engine cache)
    means the next ``db.*`` call rebuilds the engine and re-runs the owner seed
    with whatever ``CLAZZZIKS_ADMIN_EMAIL`` the test has set by then.
    """
    monkeypatch.setenv("CLAZZZIKS_DATABASE_URL", TEST_DATABASE_URL)

    engine = create_engine(TEST_DATABASE_URL, future=True)
    db.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE track_cache, vip, download_log RESTART IDENTITY"))
    engine.dispose()

    db._engines.clear()
    yield
    db._engines.clear()


@pytest.fixture
def client():
    return TestClient(create_app())
