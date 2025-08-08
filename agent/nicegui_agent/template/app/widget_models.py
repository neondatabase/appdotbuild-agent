"""Dynamic widget models for customizable UI"""
from sqlmodel import SQLModel, Field, JSON, Column
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from enum import Enum
from pydantic import ConfigDict


class WidgetType(str, Enum):
    """Available widget types"""
    CARD = "card"
    CHART = "chart"
    TABLE = "table"
    METRIC = "metric"
    BUTTON = "button"
    TEXT = "text"
    IMAGE = "image"
    CUSTOM = "custom"


class WidgetSize(str, Enum):
    """Widget size presets"""
    SMALL = "small"  # 1/4 width
    MEDIUM = "medium"  # 1/2 width
    LARGE = "large"  # 3/4 width
    FULL = "full"  # full width


class Widget(SQLModel, table=True):
    """Widget configuration stored in database"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    type: WidgetType
    size: WidgetSize = Field(default=WidgetSize.MEDIUM)
    position: int = Field(default=0)  # Order in the layout
    page: str = Field(default="dashboard", index=True)  # Which page this widget belongs to
    
    # Widget configuration as JSON
    config: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    
    # Data source configuration
    data_source: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    
    # Widget styling
    style: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    
    # Visibility and permissions
    is_visible: bool = Field(default=True)
    is_editable: bool = Field(default=True)
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    model_config = ConfigDict(arbitrary_types_allowed=True)  # type: ignore


class WidgetTemplate(SQLModel, table=True):
    """Pre-defined widget templates users can instantiate"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: Optional[str] = None
    type: WidgetType
    default_config: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    default_style: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    category: str = Field(default="general")
    icon: Optional[str] = None
    
    model_config = ConfigDict(arbitrary_types_allowed=True)  # type: ignore


class UserWidgetPreset(SQLModel, table=True):
    """User-saved widget configurations"""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)  # Can be session ID or actual user ID
    preset_name: str
    widgets: List[Dict[str, Any]] = Field(default=[], sa_column=Column(JSON))
    is_default: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    model_config = ConfigDict(arbitrary_types_allowed=True)  # type: ignore