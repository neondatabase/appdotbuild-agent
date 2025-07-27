from sqlmodel import SQLModel, Field, Relationship, JSON, Column
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any

# Persistent models (stored in database)
class User(SQLModel, table=True):
    __tablename__ = "users"  # type: ignore[assignment]
    
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, max_length=50, index=True)
    email: str = Field(unique=True, max_length=255)
    full_name: str = Field(max_length=100)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    projects: List["Project"] = Relationship(back_populates="owner")
    tasks: List["Task"] = Relationship(back_populates="assignee")
    comments: List["Comment"] = Relationship(back_populates="author")

class Project(SQLModel, table=True):
    __tablename__ = "projects"  # type: ignore[assignment]
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=200, index=True)
    description: Optional[str] = Field(default=None, max_length=1000)
    owner_id: int = Field(foreign_key="users.id")
    status: str = Field(default="active", max_length=20)  # active, archived, completed
    budget: Decimal = Field(default=Decimal('0'), max_digits=10, decimal_places=2)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    due_date: Optional[datetime] = Field(default=None)
    
    # JSON field for flexible metadata
    metadata: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    tags: List[str] = Field(default=[], sa_column=Column(JSON))
    
    # Relationships
    owner: User = Relationship(back_populates="projects")
    tasks: List["Task"] = Relationship(back_populates="project")

class Task(SQLModel, table=True):
    __tablename__ = "tasks"  # type: ignore[assignment]
    
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    project_id: int = Field(foreign_key="projects.id", index=True)
    assignee_id: Optional[int] = Field(default=None, foreign_key="users.id")
    priority: int = Field(default=0, ge=0, le=5)  # 0-5 priority scale
    completed: bool = Field(default=False)
    completed_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    due_date: Optional[datetime] = Field(default=None)
    
    # Relationships
    project: Project = Relationship(back_populates="tasks")
    assignee: Optional[User] = Relationship(back_populates="tasks")
    comments: List["Comment"] = Relationship(back_populates="task")

class Comment(SQLModel, table=True):
    __tablename__ = "comments"  # type: ignore[assignment]
    
    id: Optional[int] = Field(default=None, primary_key=True)
    content: str = Field(max_length=1000)
    task_id: int = Field(foreign_key="tasks.id", index=True)
    author_id: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    edited_at: Optional[datetime] = Field(default=None)
    
    # Relationships
    task: Task = Relationship(back_populates="comments")
    author: User = Relationship(back_populates="comments")

# Non-persistent schemas (for validation, forms, API requests/responses)
class UserCreate(SQLModel, table=False):
    username: str = Field(max_length=50)
    email: str = Field(max_length=255)
    full_name: str = Field(max_length=100)
    password: str = Field(min_length=8)  # Not stored in User model

class UserUpdate(SQLModel, table=False):
    username: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=255)
    full_name: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = Field(default=None)

class ProjectCreate(SQLModel, table=False):
    name: str = Field(max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    budget: Decimal = Field(default=Decimal('0'))
    due_date: Optional[datetime] = Field(default=None)
    tags: List[str] = Field(default=[])

class TaskCreate(SQLModel, table=False):
    title: str = Field(max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    project_id: int
    assignee_id: Optional[int] = Field(default=None)
    priority: int = Field(default=0, ge=0, le=5)
    due_date: Optional[datetime] = Field(default=None)

class TaskUpdate(SQLModel, table=False):
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    assignee_id: Optional[int] = Field(default=None)
    priority: Optional[int] = Field(default=None, ge=0, le=5)
    completed: Optional[bool] = Field(default=None)
    due_date: Optional[datetime] = Field(default=None)

# Response schemas with computed fields
class TaskResponse(SQLModel, table=False):
    id: int
    title: str
    description: Optional[str]
    project_id: int
    assignee_id: Optional[int]
    priority: int
    completed: bool
    completed_at: Optional[datetime]
    created_at: datetime
    due_date: Optional[datetime]
    
    # Additional computed fields
    is_overdue: bool = Field(default=False)
    assignee_name: Optional[str] = Field(default=None)
    project_name: str
    comment_count: int = Field(default=0)

class ProjectStats(SQLModel, table=False):
    total_tasks: int = Field(default=0)
    completed_tasks: int = Field(default=0)
    overdue_tasks: int = Field(default=0)
    completion_rate: Decimal = Field(default=Decimal('0'))
    total_budget_used: Decimal = Field(default=Decimal('0'))