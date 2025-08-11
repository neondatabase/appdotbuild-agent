"""
Dashboard Generation Examples for NiceGUI Agent

These examples demonstrate how to generate dashboard applications with widgets.
"""

DASHBOARD_EXAMPLES = {
    "analytics_dashboard": """
Create an analytics dashboard with the following widgets:
1. Key Metrics row showing total users, revenue, conversion rate, and churn rate
2. Line chart showing user growth over the last 12 months
3. Bar chart showing revenue by product category
4. Table showing top 10 customers by revenue
5. Pie chart showing traffic sources distribution
""",
    
    "sales_dashboard": """
Build a sales performance dashboard that includes:
1. Metric widgets for today's sales, monthly target progress, and average order value
2. Real-time sales activity feed showing recent transactions
3. Chart comparing this month's sales to last month
4. Leaderboard table showing top performing sales reps
5. Geographic heat map of sales by region
""",
    
    "inventory_dashboard": """
Design an inventory management dashboard with:
1. Stock level indicators for low inventory items (metric widgets)
2. Bar chart showing inventory turnover by category
3. Table of products needing reorder
4. Timeline chart of inventory movements
5. Alert cards for critical stock situations
""",
    
    "customer_service_dashboard": """
Implement a customer service dashboard featuring:
1. Open tickets count, average response time, and satisfaction score metrics
2. Real-time ticket queue table
3. Chart showing ticket volume trends over time
4. Agent performance metrics grid
5. Priority alerts for escalated issues
""",
    
    "financial_dashboard": """
Create a financial overview dashboard with:
1. Revenue, expenses, profit margin, and cash flow metric cards
2. Income statement summary table
3. Monthly P&L trend chart
4. Budget vs actual comparison charts
5. Accounts receivable aging table
""",
    
    "project_management_dashboard": """
Build a project tracking dashboard including:
1. Active projects count, on-time delivery rate, and resource utilization metrics
2. Gantt chart widget for project timelines
3. Task status distribution pie chart
4. Team member workload table
5. Upcoming milestones cards
""",
    
    "marketing_dashboard": """
Design a marketing performance dashboard with:
1. Website traffic, conversion rate, and CAC metric widgets
2. Campaign performance comparison chart
3. Social media engagement metrics grid
4. Email campaign results table
5. ROI by channel bar chart
""",
    
    "hr_dashboard": """
Implement an HR analytics dashboard featuring:
1. Employee count, turnover rate, and average tenure metrics
2. Department headcount distribution chart
3. Recruitment pipeline funnel chart
4. Employee satisfaction survey results
5. Upcoming reviews and anniversaries table
""",
    
    "iot_monitoring_dashboard": """
Create an IoT device monitoring dashboard with:
1. Active devices, data points collected, and system uptime metrics
2. Real-time device status grid with health indicators
3. Sensor data time series charts
4. Alert history table
5. Device location map widget
""",
    
    "ecommerce_dashboard": """
Build an e-commerce operations dashboard including:
1. Today's orders, cart abandonment rate, and average cart value metrics
2. Sales by hour heat map
3. Best selling products table
4. Customer acquisition funnel chart
5. Shipping status distribution pie chart
"""
}

WIDGET_GENERATION_PATTERNS = {
    "metric_pattern": """
# Generate a metric widget showing a KPI
def create_kpi_widget(name: str, title: str, value: Any, icon: str, change: float = None):
    config = {
        "title": title,
        "value": value,
        "icon": icon
    }
    if change is not None:
        config["change"] = change
    
    return WidgetService.create_widget(
        name=name,
        type=WidgetType.METRIC,
        size=WidgetSize.SMALL,
        config=config
    )
""",
    
    "chart_pattern": """
# Generate a chart widget from data
def create_chart_widget(name: str, title: str, chart_type: str, data: dict):
    return WidgetService.create_widget(
        name=name,
        type=WidgetType.CHART,
        size=WidgetSize.LARGE,
        config={
            "chart_type": chart_type,
            "title": title,
            "data": data,
            "show_legend": True
        }
    )
""",
    
    "table_pattern": """
# Generate a table widget from query results
def create_table_from_query(name: str, title: str, model_class, limit: int = 10):
    with get_session() as session:
        items = session.exec(
            select(model_class).limit(limit)
        ).all()
        
        # Convert to table format
        columns = [
            {"name": col, "label": col.replace("_", " ").title(), "field": col}
            for col in model_class.__table__.columns.keys()
        ]
        
        rows = [
            {col: getattr(item, col) for col in model_class.__table__.columns.keys()}
            for item in items
        ]
        
        return WidgetService.create_widget(
            name=name,
            type=WidgetType.TABLE,
            size=WidgetSize.FULL,
            config={
                "title": title,
                "columns": columns,
                "rows": rows
            }
        )
""",
    
    "realtime_pattern": """
# Generate a widget that updates in real-time
def create_realtime_widget(name: str, update_interval: int = 5):
    widget = WidgetService.create_widget(
        name=name,
        type=WidgetType.CUSTOM,
        size=WidgetSize.MEDIUM,
        config={
            "html": '<div id="realtime-data"></div>',
            "javascript": f'''
                setInterval(() => {{
                    fetch('/api/realtime-data')
                        .then(r => r.json())
                        .then(data => {{
                            document.getElementById('realtime-data').innerHTML = 
                                `<h3>${{data.title}}</h3><p>${{data.value}}</p>`;
                        }});
                }}, {update_interval * 1000});
            '''
        }
    )
    return widget
""",
    
    "composite_dashboard_pattern": """
# Generate a complete dashboard with multiple widgets
def generate_dashboard(page_name: str = "dashboard"):
    # Clear existing widgets for this page
    existing = WidgetService.get_widgets_for_page(page_name)
    for widget in existing:
        WidgetService.delete_widget(widget.id)
    
    # Create metric widgets row
    metrics = [
        ("Total Users", "users_count", 1234, "people", 5.2),
        ("Revenue", "revenue", 45678, "attach_money", 12.3),
        ("Conversion", "conversion", 3.2, "trending_up", -1.5),
        ("Churn Rate", "churn", 2.1, "trending_down", -0.8)
    ]
    
    for title, name, value, icon, change in metrics:
        create_kpi_widget(name, title, value, icon, change)
    
    # Create main chart
    create_chart_widget(
        "main_chart",
        "Monthly Trends",
        "line",
        {
            "x": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
            "y": [100, 120, 115, 140, 155, 180]
        }
    )
    
    # Create data table
    create_table_from_query(
        "recent_items",
        "Recent Activity",
        YourModel,  # Replace with actual model
        limit=10
    )
    
    return WidgetService.get_widgets_for_page(page_name)
"""
}

DASHBOARD_PROMPT_TEMPLATE = """
When generating a dashboard application, follow these steps:

1. **Identify Required Widgets**: Based on the user's request, determine what types of widgets are needed:
   - Metrics/KPIs → Use METRIC widgets
   - Trends/comparisons → Use CHART widgets  
   - Data lists → Use TABLE widgets
   - Status/alerts → Use CARD or TEXT widgets
   - Actions → Use BUTTON widgets

2. **Plan Widget Layout**: Organize widgets by importance and relationships:
   - Place key metrics at the top in a row (SMALL size)
   - Main visualizations in the middle (LARGE size)
   - Supporting tables/lists below (FULL or LARGE size)
   - Actions and controls on the side or bottom

3. **Implement Data Sources**: For each widget, determine the data source:
   - Database queries using SQLModel
   - Calculated metrics from business logic
   - External API calls
   - Real-time data streams

4. **Create Widget Configurations**: Generate appropriate configs for each widget type:
   - Metric: title, value, icon, change percentage
   - Chart: type, title, data arrays, axis labels
   - Table: columns definition, rows data
   - Card: title, subtitle, content HTML

5. **Initialize Widgets**: In the startup.py file:
   ```python
   def startup():
       create_tables()
       # Initialize widget system
       WidgetService.initialize_default_widgets()
       # Create dashboard widgets
       create_dashboard_widgets()
   ```

6. **Add Dashboard Page**: Create a page that renders the widget dashboard:
   ```python
   @ui.page("/dashboard")
   def dashboard():
       manager = WidgetManager()
       manager.render_dashboard()
   ```

Remember to:
- Use consistent naming for widgets
- Include error handling for data fetching
- Add refresh capabilities for real-time data
- Implement responsive layouts
- Provide edit mode for admins
"""