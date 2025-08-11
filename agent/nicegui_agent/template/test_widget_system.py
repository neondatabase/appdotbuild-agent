#!/usr/bin/env python3
"""Test script for the widget system"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'template'))

from app.database import create_tables
from app.widget_models import WidgetType, WidgetSize
from app.widget_service import WidgetService

def test_widget_system():
    """Test the widget system functionality"""
    print("Testing Widget System...")
    
    # Create tables
    create_tables()
    print("✓ Database tables created")
    
    # Initialize default widgets
    WidgetService.initialize_default_widgets()
    print("✓ Default widgets initialized")
    
    # Get widgets for dashboard
    widgets = WidgetService.get_widgets_for_page("dashboard")
    print(f"✓ Found {len(widgets)} widgets on dashboard")
    
    # Create a new widget
    new_widget = WidgetService.create_widget(
        name="Test Widget",
        type=WidgetType.TEXT,
        size=WidgetSize.MEDIUM,
        config={"content": "This is a test widget", "markdown": False}
    )
    print(f"✓ Created new widget: {new_widget.name} (ID: {new_widget.id})")
    
    # Update the widget
    updated = WidgetService.update_widget(
        new_widget.id,
        name="Updated Test Widget",
        config={"content": "Updated content", "markdown": True}
    )
    print(f"✓ Updated widget: {updated.name}")
    
    # Get all widgets again
    widgets = WidgetService.get_widgets_for_page("dashboard")
    print(f"✓ Total widgets: {len(widgets)}")
    
    # List all widgets
    print("\nCurrent widgets:")
    for widget in widgets:
        print(f"  - {widget.name} ({widget.type.value}, {widget.size.value})")
    
    # Delete the test widget
    WidgetService.delete_widget(new_widget.id)
    print("✓ Deleted test widget")
    
    print("\n✅ Widget system test completed successfully!")

if __name__ == "__main__":
    test_widget_system()