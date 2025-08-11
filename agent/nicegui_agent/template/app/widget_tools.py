"""
Widget tools for agent code generation
======================================

This module provides helper functions for the agent to easily create and configure
widgets with data sources during code generation.

IMPORTANT FOR AGENT:
- Always use these helper functions when creating widgets
- Always connect widgets to appropriate data sources when available
- Widgets should display real data from the database or external sources
- Use DataSourceService to introspect available tables and create data-driven widgets

Example usage for agent:
```python
from app.widget_tools import WidgetTools

# Create a metric widget with data from database
WidgetTools.create_metric_from_query(
    name="Total Sales",
    query="SELECT SUM(amount) as total FROM sales",
    icon="trending_up"
)

# Create a chart with data
WidgetTools.create_chart_from_table(
    name="Sales Trend",
    table="sales",
    x_column="date",
    y_column="amount",
    chart_type="line"
)

# Create a table widget
WidgetTools.create_table_from_query(
    name="Recent Orders",
    query="SELECT * FROM orders ORDER BY created_at DESC LIMIT 10"
)
```
"""

import logging
import os
from typing import Dict, Any, List, Optional
from app.widget_service import WidgetService
from app.widget_models import Widget, WidgetType, WidgetSize
from app.data_source_service import DataSourceService

logger = logging.getLogger(__name__)


class WidgetTools:
    """Helper tools for agent to create and configure widgets with data"""
    @staticmethod
    def _is_databricks_configured() -> bool:
        return bool(os.environ.get("DATABRICKS_HOST") and os.environ.get("DATABRICKS_TOKEN"))
    
    @staticmethod
    def create_metric_from_query(
        name: str,
        query: str,
        title: Optional[str] = None,
        icon: str = "trending_up",
        page: str = "dashboard",
        size: WidgetSize = WidgetSize.SMALL
    ) -> Widget:
        """
        Create a metric widget that displays a single value from a SQL query.
        
        The query should return a single numeric value.
        Example: "SELECT COUNT(*) FROM users WHERE active = true"
        """
        config = {
            "title": title or name,
            "icon": icon,
            "query": query
        }
        
        data_source = {
            "type": "databricks_query" if WidgetTools._is_databricks_configured() else "query",
            "query": query,
            "refresh_interval": 60  # Refresh every minute
        }
        
        # Enforce creation via WidgetService with a proper data_source
        return WidgetService.create_widget(
            name=name,
            type=WidgetType.METRIC,
            page=page,
            size=size,
            config=config,
            data_source=data_source
        )
    
    @staticmethod
    def create_chart_from_table(
        name: str,
        table: str,
        x_column: str,
        y_column: str,
        chart_type: str = "line",
        title: Optional[str] = None,
        page: str = "dashboard",
        size: WidgetSize = WidgetSize.MEDIUM,
        limit: int = 100
    ) -> Widget:
        """
        Create a chart widget from a database table.
        
        Args:
            table: Name of the database table
            x_column: Column to use for X axis
            y_column: Column to use for Y axis
            chart_type: One of "line", "bar", "pie"
        """
        config = {
            "title": title or name,
            "chart_type": chart_type,
            "x_axis": x_column,
            "y_axis": y_column,
            "show_legend": True
        }
        
        # Prefer direct Databricks query when configured to ensure real data
        if WidgetTools._is_databricks_configured():
            query = f"SELECT {x_column}, {y_column} FROM {table} ORDER BY {x_column} LIMIT {limit}"
            data_source = {
                "type": "databricks_query",
                "query": query,
                "refresh_interval": 60,
            }
        else:
            data_source = {
                "type": "table",
                "table": table,
                "columns": [x_column, y_column],
                "limit": limit,
                "order_by": x_column
            }
        
        # Enforce creation via WidgetService with a proper data_source
        return WidgetService.create_widget(
            name=name,
            type=WidgetType.CHART,
            page=page,
            size=size,
            config=config,
            data_source=data_source
        )
    
    @staticmethod
    def create_table_from_query(
        name: str,
        query: str,
        title: Optional[str] = None,
        page: str = "dashboard",
        size: WidgetSize = WidgetSize.LARGE,
        columns: Optional[List[Dict[str, str]]] = None
    ) -> Widget:
        """
        Create a table widget from a SQL query.
        
        Args:
            query: SQL query to fetch data
            columns: Optional list of column configurations
                    [{"name": "id", "label": "ID", "sortable": True}, ...]
        """
        config = {
            "title": title or name,
            "query": query,
            "columns": columns or [],
            "pagination": True,
            "rows_per_page": 10
        }
        
        data_source = {
            "type": "databricks_query" if WidgetTools._is_databricks_configured() else "query",
            "query": query,
            "refresh_interval": 30
        }
        
        # Enforce creation via WidgetService with a proper data_source
        return WidgetService.create_widget(
            name=name,
            type=WidgetType.TABLE,
            page=page,
            size=size,
            config=config,
            data_source=data_source
        )
    
    @staticmethod
    def create_widgets_for_table(table_name: str, page: str = "dashboard") -> List[Widget]:
        """
        Automatically create a set of widgets for a database table.
        This is useful for quickly creating a dashboard for a table.
        
        Creates:
        - A metric showing row count
        - A table showing recent records
        - Charts for numeric columns (if applicable)
        """
        widgets = []
        
        # Get table information
        tables = DataSourceService.get_available_tables()
        table_info = next((t for t in tables if t["name"] == table_name), None)
        
        if not table_info:
            logger.warning(f"Table {table_name} not found")
            return widgets
        
        # Create row count metric
        count_widget = WidgetTools.create_metric_from_query(
            name=f"{table_name} Count",
            query=f"SELECT COUNT(*) FROM {table_name}",
            title=f"Total {table_name.title()}",
            icon="storage",
            size=WidgetSize.SMALL
        )
        widgets.append(count_widget)
        
        # Create table widget for recent records
        table_widget = WidgetTools.create_table_from_query(
            name=f"Recent {table_name}",
            query=f"SELECT * FROM {table_name} ORDER BY id DESC LIMIT 20",
            title=f"Recent {table_name.title()} Records",
            size=WidgetSize.LARGE
        )
        widgets.append(table_widget)
        
        # Find numeric columns for charts
        numeric_columns = [
            col for col in table_info["columns"] 
            if col["type"] in ["integer", "bigint", "numeric", "real", "double precision"]
        ]
        
        # Find date/time columns for x-axis
        date_columns = [
            col for col in table_info["columns"]
            if "date" in col["type"] or "time" in col["type"]
        ]
        
        # Create a chart if we have numeric and date columns
        if numeric_columns and date_columns:
            chart_widget = WidgetTools.create_chart_from_table(
                name=f"{table_name} Trend",
                table=table_name,
                x_column=date_columns[0]["name"],
                y_column=numeric_columns[0]["name"],
                chart_type="line",
                title=f"{table_name.title()} Trend",
                size=WidgetSize.MEDIUM
            )
            widgets.append(chart_widget)
        
        return widgets
    
    @staticmethod
    def create_dashboard_from_schema(page: str = "dashboard") -> List[Widget]:
        """
        Automatically create a complete dashboard based on all available tables.
        This is useful for quickly setting up a monitoring dashboard.
        """
        widgets = []
        tables = DataSourceService.get_available_tables()
        
        for table in tables:
            # Skip system tables
            if table["name"].startswith("pg_") or table["name"] in ["widget", "widgettemplate", "userwidgetpreset"]:
                continue
            
            # Create widgets for this table
            table_widgets = WidgetTools.create_widgets_for_table(table["name"], page)
            widgets.extend(table_widgets)
        
        logger.info(f"Created {len(widgets)} widgets for dashboard")
        return widgets


# Helper function for agent to use during generation
def setup_data_driven_dashboard():
    """
    Helper function for agent to quickly set up a data-driven dashboard.
    Call this after creating your data models.
    """
    from app.widget_tools import WidgetTools
    
    # Clear existing widgets
    from app.widget_service import WidgetService
    widgets = WidgetService.get_widgets_for_page("dashboard")
    for widget in widgets:
        if widget.id:
            WidgetService.delete_widget(widget.id)
    
    # Create new data-driven widgets
    WidgetTools.create_dashboard_from_schema("dashboard")
    
    logger.info("Data-driven dashboard created successfully")