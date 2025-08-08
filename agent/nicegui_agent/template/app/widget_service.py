"""Service for managing dynamic widgets"""

import logging
from typing import List, Optional, Dict, Any
from sqlmodel import Session, select, col
from sqlalchemy import desc
from app.database import engine
from app.widget_models import Widget, WidgetTemplate, UserWidgetPreset, WidgetType, WidgetSize
from datetime import datetime

logger = logging.getLogger(__name__)


class WidgetService:
    """Service for managing widgets in the database"""

    @staticmethod
    def get_widgets_for_page(page: str = "dashboard", user_id: Optional[str] = None) -> List[Widget]:
        """Get all widgets for a specific page"""
        with Session(engine) as session:
            statement = select(Widget).where(Widget.page == page, Widget.is_visible).order_by(col(Widget.position))
            widgets = session.exec(statement).all()
            return list(widgets)
    
    @staticmethod
    def get_all_widgets() -> List[Widget]:
        """Get all widgets"""
        with Session(engine) as session:
            widgets = session.exec(select(Widget)).all()
            return list(widgets)

    @staticmethod
    def create_widget(
        name: str,
        type: WidgetType,
        page: str = "dashboard",
        size: WidgetSize = WidgetSize.MEDIUM,
        config: Optional[Dict[str, Any]] = None,
        data_source: Optional[Dict[str, Any]] = None,
        style: Optional[Dict[str, Any]] = None,
    ) -> Widget:
        """Create a new widget"""
        with Session(engine) as session:
            # Get the next position
            max_position = session.exec(
                select(Widget.position).where(Widget.page == page).order_by(desc(col(Widget.position)))
            ).first()
            next_position = (max_position or 0) + 1

            widget = Widget(
                name=name,
                type=type,
                page=page,
                size=size,
                position=next_position,
                config=config or {},
                data_source=data_source,
                style=style or {},
            )
            session.add(widget)
            session.commit()
            session.refresh(widget)
            logger.info(f"Created widget: {widget.name} (ID: {widget.id})")
            return widget

    @staticmethod
    def update_widget(widget_id: int, **kwargs) -> Optional[Widget]:
        """Update a widget's configuration"""
        with Session(engine) as session:
            widget = session.get(Widget, widget_id)
            if not widget:
                logger.warning(f"Widget {widget_id} not found")
                return None

            for key, value in kwargs.items():
                if hasattr(widget, key):
                    setattr(widget, key, value)

            widget.updated_at = datetime.utcnow()
            session.add(widget)
            session.commit()
            session.refresh(widget)
            logger.info(f"Updated widget: {widget.name} (ID: {widget.id})")
            return widget

    @staticmethod
    def delete_widget(widget_id: int) -> bool:
        """Delete a widget"""
        with Session(engine) as session:
            widget = session.get(Widget, widget_id)
            if not widget:
                logger.warning(f"Widget {widget_id} not found")
                return False

            session.delete(widget)
            session.commit()
            logger.info(f"Deleted widget: {widget.name} (ID: {widget_id})")
            return True

    @staticmethod
    def reorder_widgets(page: str, widget_ids: List[int]) -> bool:
        """Reorder widgets on a page"""
        with Session(engine) as session:
            for position, widget_id in enumerate(widget_ids):
                widget = session.get(Widget, widget_id)
                if widget and widget.page == page:
                    widget.position = position
                    session.add(widget)
            session.commit()
            logger.info(f"Reordered widgets on page: {page}")
            return True

    @staticmethod
    def get_widget_templates() -> List[WidgetTemplate]:
        """Get all available widget templates"""
        with Session(engine) as session:
            templates = session.exec(select(WidgetTemplate)).all()
            return list(templates)

    @staticmethod
    def create_widget_from_template(
        template_id: int, page: str = "dashboard", name: Optional[str] = None
    ) -> Optional[Widget]:
        """Create a widget from a template"""
        with Session(engine) as session:
            template = session.get(WidgetTemplate, template_id)
            if not template:
                logger.warning(f"Template {template_id} not found")
                return None

            return WidgetService.create_widget(
                name=name or template.name,
                type=template.type,
                page=page,
                config=template.default_config,
                style=template.default_style,
            )

    @staticmethod
    def save_user_preset(user_id: str, preset_name: str, page: str = "dashboard") -> UserWidgetPreset:
        """Save current widget configuration as a user preset"""
        widgets = WidgetService.get_widgets_for_page(page)
        widget_data = [
            {
                "name": w.name,
                "type": w.type,
                "size": w.size,
                "position": w.position,
                "config": w.config,
                "style": w.style,
            }
            for w in widgets
        ]

        with Session(engine) as session:
            preset = UserWidgetPreset(user_id=user_id, preset_name=preset_name, widgets=widget_data)
            session.add(preset)
            session.commit()
            session.refresh(preset)
            logger.info(f"Saved preset: {preset_name} for user: {user_id}")
            return preset

    @staticmethod
    def load_user_preset(preset_id: int, page: str = "dashboard") -> bool:
        """Load a user preset, replacing current widgets"""
        with Session(engine) as session:
            preset = session.get(UserWidgetPreset, preset_id)
            if not preset:
                logger.warning(f"Preset {preset_id} not found")
                return False

            # Delete existing widgets for the page
            existing_widgets = session.exec(select(Widget).where(Widget.page == page)).all()
            for widget in existing_widgets:
                session.delete(widget)

            # Create widgets from preset
            for widget_data in preset.widgets:
                widget = Widget(
                    name=widget_data["name"],
                    type=widget_data["type"],
                    size=widget_data.get("size", WidgetSize.MEDIUM),
                    position=widget_data.get("position", 0),
                    page=page,
                    config=widget_data.get("config", {}),
                    style=widget_data.get("style", {}),
                )
                session.add(widget)

            session.commit()
            logger.info(f"Loaded preset: {preset.preset_name}")
            return True

    @staticmethod
    def initialize_default_widgets(create_samples: bool = True):
        """Initialize default widgets if none exist"""
        # Check if widgets already exist
        existing = WidgetService.get_all_widgets()
        if existing:
            logger.info(f"Found {len(existing)} existing widgets")
            return
        
        if not create_samples:
            logger.info("Skipping widget creation (create_samples=False)")
            return
            
        logger.info("No widgets found, creating sample widgets...")
        
        # Use the widget generator to create comprehensive sample widgets
        from app.widget_generator import WidgetGenerator
        WidgetGenerator.generate_sample_widgets()
        
        logger.info("Sample widgets created successfully")
