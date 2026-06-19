"""Shared pytest fixtures for the FastAPI app tests."""

import pytest
from fastapi.testclient import TestClient

from clazzziks.web import create_app


@pytest.fixture
def client():
    return TestClient(create_app())
