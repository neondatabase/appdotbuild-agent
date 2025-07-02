import os
from sqlmodel import SQLModel, create_engine, Session

# Import all models to ensure they're registered. ToDo: replace with specific imports when possible.
from app.models import *  # noqa: F401, F403

DATABASE_URL = os.environ.get("APP_DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/postgres")
ENGINE = create_engine(DATABASE_URL, echo=True)

def create_tables():
    SQLModel.metadata.create_all(ENGINE)

def get_session():
    with Session(ENGINE) as session:
        yield session
