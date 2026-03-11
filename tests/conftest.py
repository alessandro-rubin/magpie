"""Pytest fixtures — in-memory SQLite for isolated tests."""

import pytest

from magpie.db.connection import get_in_memory_connection


@pytest.fixture
def db():
    """Provide a fresh in-memory SQLite connection with full schema."""
    conn = get_in_memory_connection()
    yield conn
    conn.close()
