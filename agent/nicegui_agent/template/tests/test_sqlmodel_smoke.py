"""Smoke test for SQLModel database setup."""
import pytest
from sqlmodel import SQLModel, text

from app.database import create_tables, ENGINE
from app import models

@pytest.mark.sqlmodel
def test_sqlmodel_smoke():
    """Single smoke test to validate SQLModel setup works end-to-end."""

    create_tables()
    
    # Check tables actually exist in the database
    with ENGINE.connect() as conn:
        # PostgreSQL-specific query to list tables
        result = conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ))
        db_tables = {row[0] for row in result}
    
    # Verify we have tables and they match our models
    assert len(db_tables) > 0, "No tables found in database"
    
    # Check that all our table models exist in DB
    for table_name in SQLModel.metadata.tables:
        assert table_name in db_tables, f"Table '{table_name}' not found in database"
