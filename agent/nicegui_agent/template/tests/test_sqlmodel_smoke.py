"""Smoke test for SQLModel database setup."""
import pytest

from app.database import create_tables
from app import models

@pytest.mark.sqlmodel
def test_sqlmodel_smoke():
    """Single smoke test to validate SQLModel setup works end-to-end."""

    create_tables()
    # Quick sanity check - look for at least one table
    table_count = len([
        name for name in dir(models)
        if hasattr(getattr(models, name), "__table__")
    ])
    assert table_count > 0, f"Expected at least 1 table, found {table_count}"
