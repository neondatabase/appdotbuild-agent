"""Smoke test for SQLModel database setup."""

import pytest
from sqlmodel import SQLModel, text
import os

from app.database import create_tables, ENGINE
from app import models


@pytest.mark.sqlmodel
def test_sqlmodel_smoke():
    """Single smoke test to validate SQLModel setup works end-to-end."""

    create_tables()

    # Check tables actually exist in the database
    with ENGINE.connect() as conn:
        # PostgreSQL-specific query to list tables
        result = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        db_tables = {row[0] for row in result}

    # Verify we have tables and they match our models
    assert len(db_tables) > 0, "No tables found in database"

    # Check that all our table models exist in DB
    for table_name in SQLModel.metadata.tables:
        assert table_name in db_tables, f"Table '{table_name}' not found in database"


DATABRICKS_HOST = os.environ.get("DATABRICKS_HOST")
DATABRICKS_TOKEN = os.environ.get("DATABRICKS_TOKEN")


@pytest.mark.sqlmodel
@pytest.mark.skipif(not DATABRICKS_HOST or not DATABRICKS_TOKEN, reason="Databricks credentials not set")
def test_databricks_models():
    from app.dbrx import DatabricksModel  # only import if credentials are set

    for model_name in dir(models):
        model = getattr(models, model_name)
        if issubclass(model, DatabricksModel) and model_name != "DatabricksModel":
            data = model.fetch()

            assert len(data) > 0, f"No data found for model {model_name}"
            assert isinstance(data, list), f"Data for model {model_name} is not a list"
