"""
Default data models for the application
"""
from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class ExampleModel(SQLModel, table=True):
    __tablename__ = "examples"  # type: ignore[assignment]
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    description: str = Field(default="", max_length=500)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)