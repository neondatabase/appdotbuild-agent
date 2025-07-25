import os
from sqlmodel import SQLModel, create_engine, Session

# Import all models to ensure they're registered. ToDo: replace with specific imports when possible.
from app.models import *  # noqa: F401, F403

DATABASE_URL = os.environ.get("APP_DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/postgres")
ENGINE = create_engine(DATABASE_URL, connect_args={"connect_timeout": 15, "options": "-c statement_timeout=1000"})


def create_tables():
    SQLModel.metadata.create_all(ENGINE)


def get_session():
    return Session(ENGINE)


def reset_db():
    """Wipe all tables in the database. Use with caution - for testing only!"""
    SQLModel.metadata.drop_all(ENGINE)
    SQLModel.metadata.create_all(ENGINE)
