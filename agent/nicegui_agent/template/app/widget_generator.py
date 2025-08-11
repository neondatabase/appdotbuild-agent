"""
Widget Generator for creating data-driven widgets programmatically.
This module is used by the agent during code generation and migration.
"""

from typing import Dict, Any, List, Optional
from app.widget_models import WidgetType, WidgetSize
from app.widget_service import WidgetService
import logging

logger = logging.getLogger(__name__)


class WidgetGenerator:
    """Generate widgets programmatically for dashboards"""
    
    @staticmethod
    def create_metric_widget(
        name: str,
        title: str,
        value: Any = None,
        icon: str = "trending_up",
        change_percent: Optional[float] = None,
        size: WidgetSize = WidgetSize.SMALL,
        page: str = "dashboard",
        data_source: Optional[Dict] = None
    ) -> None:
        """Create a metric/KPI widget with data source"""
        config = {
            "title": title,
            "icon": icon,
        }
        if value is not None:
            config["value"] = value
        if change_percent is not None:
            config["change"] = change_percent
            
        WidgetService().create_widget(
            name=name,
            type=WidgetType.METRIC,
            size=size,
            page=page,
            config=config,
            data_source=data_source  # Pass data_source separately
        )
        logger.info(f"Created metric widget: {name}")
    
    @staticmethod
    def create_chart_widget(
        name: str,
        title: str,
        chart_type: str = "line",
        data: Optional[Dict[str, List]] = None,
        size: WidgetSize = WidgetSize.MEDIUM,
        page: str = "dashboard",
        data_source: Optional[Dict] = None
    ) -> None:
        """Create a chart widget with data source"""
        config = {
            "title": title,
            "chart_type": chart_type,
            "show_legend": True,
        }
        
        # NEVER put data in config - use data_source instead
        if data and not data_source:
            logger.warning(f"Chart widget {name} created with static data - converting to query")
            # Convert static data to a data source query if possible
            from app.data_source_service import DataSourceService
            tables = DataSourceService.get_available_tables()
            if tables:
                first_table = tables[0]["name"]
                data_source = {
                    "type": "query",
                    "query": f"SELECT * FROM {first_table} LIMIT 10"
                }
            
        WidgetService().create_widget(
            name=name,
            type=WidgetType.CHART,
            size=size,
            page=page,
            config=config,
            data_source=data_source  # Pass data_source separately
        )
        logger.info(f"Created chart widget: {name}")
    
    @staticmethod
    def create_table_widget(
        name: str,
        title: str,
        columns: Optional[List[Dict]] = None,
        rows: Optional[List[Dict]] = None,
        size: WidgetSize = WidgetSize.LARGE,
        page: str = "dashboard",
        data_source: Optional[Dict] = None
    ) -> None:
        """Create a table widget with data source"""
        config = {
            "title": title,
        }
        
        # NEVER put columns/rows in config - use data_source instead
        if (columns or rows) and not data_source:
            logger.warning(f"Table widget {name} created with static data - converting to query")
            # Convert static data to a data source query
            from app.data_source_service import DataSourceService
            tables = DataSourceService.get_available_tables()
            if tables:
                first_table = tables[0]["name"]
                data_source = {
                    "type": "query",
                    "query": f"SELECT * FROM {first_table} LIMIT 20"
                }
        
        # Columns and rows will come from data_source query execution
        WidgetService().create_widget(
            name=name,
            type=WidgetType.TABLE,
            size=size,
            page=page,
            config=config,
            data_source=data_source  # Pass data_source separately
        )
        logger.info(f"Created table widget: {name}")
    
    @staticmethod
    def create_text_widget(
        name: str,
        content: str,
        markdown: bool = True,
        size: WidgetSize = WidgetSize.MEDIUM,
        page: str = "dashboard"
    ) -> None:
        """Create a text/markdown widget"""
        config = {
            "content": content,
            "markdown": markdown,
        }
        
        WidgetService().create_widget(
            name=name,
            type=WidgetType.TEXT,
            size=size,
            page=page,
            config=config
        )
        logger.info(f"Created text widget: {name}")
    
    @staticmethod
    def generate_sample_widgets():
        """Generate sample widgets with data source support"""
        try:
            # Import data tools
            from app.data_source_service import DataSourceService
            
            # Check for available data tables
            tables = DataSourceService.get_available_tables()
            data_tables = [t for t in tables if t["name"] not in ["widget", "widgettemplate", "userwidgetpreset"]]
            
            if data_tables:
                # If we have data tables, create data-driven widgets
                logger.info(f"Found {len(data_tables)} data tables, creating data-driven widgets")
                from app.widget_tools import WidgetTools
                
                # Create widgets for the first available table
                first_table = data_tables[0]["name"]
                WidgetTools.create_widgets_for_table(first_table)
                
                # Add a welcome message
                WidgetGenerator.create_text_widget(
                    name="Dashboard Overview",
                    content=f"""
## 📊 Data-Driven Dashboard

This dashboard is connected to your database tables:
- **{len(data_tables)} tables** available
- **Live data** from {first_table}
- **Auto-refresh** enabled

Use **Edit Widgets** to customize or add more data visualizations!
                    """,
                    markdown=True,
                    size=WidgetSize.FULL
                )
            else:
                # No data tables, create sample widgets
                logger.info("No data tables found, creating sample widgets")
                WidgetGenerator.create_text_widget(
                    name="Welcome Message",
                    content="""
## 👋 Welcome to Your Custom Dashboard!

This dashboard includes **customizable widgets** that you can:
- ✏️ Edit in real-time
- ➕ Add new widgets
- 🗑️ Delete unwanted widgets
- 📊 Connect to data sources

Toggle **Edit Widgets** mode to start customizing!
                    """,
                    markdown=True,
                    size=WidgetSize.FULL
                )
            
            # Create data-driven metric widgets using WidgetTools
            from app.widget_tools import WidgetTools
            
            # Get the first available table for queries
            first_table = data_tables[0]["name"] if data_tables else "widget"
            
            # Create metrics with real queries
            WidgetTools.create_metric_from_query(
                name="Total Revenue",
                query=f"SELECT COUNT(*) as value FROM {first_table}",
                title="Total Records",
                icon="storage",
                size=WidgetSize.SMALL
            )
            
            WidgetTools.create_metric_from_query(
                name="Active Users",
                query=f"SELECT COUNT(DISTINCT id) as value FROM {first_table}",
                title="Unique Records",
                icon="people",
                size=WidgetSize.SMALL
            )
            
            WidgetTools.create_metric_from_query(
                name="Conversion Rate",
                query=f"SELECT CAST(COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM {first_table}), 0) AS INTEGER) as value FROM {first_table} WHERE id IS NOT NULL",
                title="Data Quality %",
                icon="trending_up",
                size=WidgetSize.SMALL
            )
            
            WidgetTools.create_metric_from_query(
                name="Avg Order Value",
                query=f"SELECT MAX(id) as value FROM {first_table}",
                title="Latest ID",
                icon="shopping_cart",
                size=WidgetSize.SMALL
            )
            
            # Create chart with real data
            if data_tables:
                WidgetTools.create_chart_from_table(
                    name="Monthly Sales Trend",
                    table=first_table,
                    x_column="id",
                    y_column="id",  # Will be replaced with actual column
                    chart_type="line",
                    title="Data Trend",
                    size=WidgetSize.LARGE
                )
            
            # Create table with real data
            WidgetTools.create_table_from_query(
                name="Top Products",
                query=f"SELECT * FROM {first_table} LIMIT 10",
                title="Recent Records",
                size=WidgetSize.MEDIUM
            )
            
            logger.info("Sample widgets generated successfully")
            
        except Exception as e:
            logger.error(f"Failed to generate sample widgets: {e}")
    
    @staticmethod
    def clear_all_widgets(page: str = "dashboard"):
        """Clear all widgets for a specific page"""
        try:
            service = WidgetService()
            widgets = service.get_widgets_for_page(page)
            for widget in widgets:
                if widget.id:
                    service.delete_widget(widget.id)
            logger.info(f"Cleared all widgets for page: {page}")
        except Exception as e:
            logger.error(f"Failed to clear widgets: {e}")