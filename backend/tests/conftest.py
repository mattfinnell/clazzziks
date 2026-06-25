"""Shared pytest fixtures for the FastAPI app tests."""

import pytest
from fastapi.testclient import TestClient

from clazzziks.web import create_app


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point the SQLite store at a fresh temp file for every test.

    Keeps the cache/VIP/rate-limit tables empty and isolated so tests never touch
    the real ``backend/clazzziks.db`` or leak state into each other.
    """
    monkeypatch.setenv("CLAZZZIKS_DB_PATH", str(tmp_path / "clazzziks.db"))


@pytest.fixture
def client():
    return TestClient(create_app())
