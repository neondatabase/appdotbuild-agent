# Widget System Guide

This application includes a powerful widget system that allows dynamic, data-driven widgets to be added, edited, and removed from the dashboard.

## Features

- **Integrated Widget Management**: Widgets appear directly on the main dashboard
- **Edit Mode**: Toggle edit mode to add, edit, or delete widgets
- **Multiple Widget Types**: Text, Metric, Chart, Table, Button, Image, Card
- **Data Integration**: Connect widgets to database tables or APIs
- **Programmatic Generation**: Create widgets via code during migration

## For Users

1. **Toggle Edit Mode**: Click "Edit Widgets" switch in the dashboard header
2. **Add Widget**: Click "Add Widget" button when in edit mode
3. **Edit Widget**: Click the edit icon on any widget when in edit mode
4. **Delete Widget**: Click the delete icon on any widget when in edit mode

## For Developers/Agents

### Creating Widgets Programmatically

Use the `WidgetGenerator` class to create widgets during code generation:

```python
from app.widget_generator import WidgetGenerator

# Create a metric widget
WidgetGenerator.create_metric_widget(
    name="Revenue",
    title="Total Revenue",
    value=125000,
    icon="attach_money",
    change_percent=12.5,
    size=WidgetSize.SMALL
)

# Create a chart widget
WidgetGenerator.create_chart_widget(
    name="Sales Trend",
    title="Monthly Sales",
    chart_type="line",
    data={
        "x": ["Jan", "Feb", "Mar"],
        "y": [100, 150, 120]
    }
)

# Create a table widget with data source
WidgetGenerator.create_table_widget(
    name="Top Products",
    title="Best Sellers",
    columns=[
        {"name": "product", "label": "Product", "field": "product"},
        {"name": "sales", "label": "Sales", "field": "sales"}
    ],
    rows=[],  # Will be populated from data source
    data_source={
        "type": "table",
        "table": "products",
        "limit": 10
    }
)
```

### Sample Widgets

To generate a complete set of sample widgets:

```python
from app.widget_generator import WidgetGenerator
WidgetGenerator.generate_sample_widgets()
```

### Clear All Widgets

To start fresh:

```python
from app.widget_generator import WidgetGenerator
WidgetGenerator.clear_all_widgets()
```

## Widget Types

1. **TEXT**: Display markdown or plain text
2. **METRIC**: Show KPI with value, icon, and change percentage
3. **CHART**: Line, bar, or pie charts with Plotly
4. **TABLE**: Data tables with pagination
5. **BUTTON**: Interactive buttons with actions
6. **IMAGE**: Display images with captions
7. **CARD**: Rich content cards

## Data Sources

Widgets can connect to:
- Static data (defined in config)
- Database tables (via data_source configuration)
- Dynamic queries (through DataSourceService)

## Best Practices

1. Generate meaningful widgets during migration based on the data model
2. Use appropriate widget sizes (SMALL, MEDIUM, LARGE, FULL)
3. Connect widgets to real data sources when available
4. Provide clear titles and icons for better UX
5. Initialize with sample widgets to demonstrate capabilities