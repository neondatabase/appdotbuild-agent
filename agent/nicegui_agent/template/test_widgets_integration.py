#!/usr/bin/env python3
"""Integration test for widget system with NiceGUI"""

import logging
from nicegui import ui
from app.database import create_tables
from app.widget_service import WidgetService
from app.widget_ui import WidgetManager
from app.widget_models import WidgetType, WidgetSize

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_widget_integration():
    """Test widget system integration"""
    
    # Initialize database
    create_tables()
    logger.info("Database initialized")
    
    # Initialize default widgets
    WidgetService.initialize_default_widgets()
    logger.info("Default widgets created")
    
    # Create some test widgets
    test_widgets = [
        {
            "name": "Sales Metrics",
            "type": WidgetType.METRIC,
            "size": WidgetSize.SMALL,
            "config": {
                "title": "Monthly Sales",
                "value": 125000,
                "icon": "attach_money",
                "change": 12.5
            }
        },
        {
            "name": "User Growth",
            "type": WidgetType.CHART,
            "size": WidgetSize.LARGE,
            "config": {
                "chart_type": "line",
                "title": "User Growth Over Time",
                "data": {
                    "x": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
                    "y": [100, 150, 230, 380, 520, 710]
                }
            }
        },
        {
            "name": "System Status",
            "type": WidgetType.CARD,
            "size": WidgetSize.MEDIUM,
            "config": {
                "title": "System Health",
                "subtitle": "All systems operational",
                "content": "<p>✅ Database: Online<br>✅ API: Responsive<br>✅ Cache: Active</p>"
            }
        }
    ]
    
    for widget_data in test_widgets:
        WidgetService.create_widget(**widget_data)
        logger.info(f"Created widget: {widget_data['name']}")
    
    logger.info("Widget integration test completed")

# Main application
@ui.page("/")
def main_page():
    """Main page with widget dashboard"""
    ui.label("Widget System Test").classes("text-3xl font-bold mb-6")
    
    with ui.tabs().classes("w-full") as tabs:
        ui.tab("Dashboard", icon="dashboard")
        ui.tab("Test Info", icon="info")
    
    with ui.tab_panels(tabs, value="Dashboard").classes("w-full"):
        with ui.tab_panel("Dashboard"):
            manager = WidgetManager()
            manager.render_dashboard()
        
        with ui.tab_panel("Test Info"):
            with ui.card().classes("p-6"):
                ui.label("Widget System Test Information").classes("text-xl font-bold mb-4")
                ui.label("This is a test application demonstrating the widget system capabilities.")
                ui.label("Features:").classes("font-bold mt-4")
                ui.html("""
                <ul class="list-disc list-inside ml-4">
                    <li>Dynamic widget creation and management</li>
                    <li>Multiple widget types (text, metrics, charts, tables, etc.)</li>
                    <li>Customizable widget sizes and layouts</li>
                    <li>Edit mode for managing widgets</li>
                    <li>Database persistence</li>
                </ul>
                """)
                
                ui.button("Run Widget Test", on_click=test_widget_integration).classes("mt-4")

if __name__ == "__main__":
    # Initialize on startup
    test_widget_integration()
    
    # Run the app
    ui.run(
        title="Widget System Test",
        port=8080,
        host="0.0.0.0",
        reload=False
    )