"""Dynamic widget renderer for NiceGUI"""
import logging
from typing import Optional, Callable
from nicegui import ui
from app.widget_models import Widget, WidgetType, WidgetSize

logger = logging.getLogger(__name__)


class WidgetRenderer:
    """Renders widgets dynamically based on their configuration"""
    
    @staticmethod
    def get_size_classes(size: WidgetSize) -> str:
        """Get CSS classes for widget size"""
        size_map = {
            WidgetSize.SMALL: "w-full md:w-1/4",
            WidgetSize.MEDIUM: "w-full md:w-1/2",
            WidgetSize.LARGE: "w-full md:w-3/4",
            WidgetSize.FULL: "w-full"
        }
        return size_map.get(size, "w-full md:w-1/2")
    
    @staticmethod
    def render_widget(widget: Widget, on_edit: Optional[Callable] = None, on_delete: Optional[Callable] = None):
        """Render a single widget based on its type and configuration"""
        size_classes = WidgetRenderer.get_size_classes(widget.size)
        
        with ui.card().classes(f"{size_classes} p-4 relative group").style(
            "; ".join([f"{k}: {v}" for k, v in widget.style.items()])
        ):
            # Add edit/delete buttons if callbacks provided
            if on_edit or on_delete:
                with ui.row().classes("absolute top-2 right-2 gap-2 opacity-0 group-hover:opacity-100 transition-opacity"):
                    if on_edit:
                        ui.button(icon="edit", on_click=lambda w=widget: on_edit(w)).props("flat dense")
                    if on_delete:
                        ui.button(icon="delete", on_click=lambda w=widget: on_delete(w)).props("flat dense color=negative")
            
            # Render widget content based on type
            match widget.type:
                case WidgetType.TEXT:
                    WidgetRenderer._render_text_widget(widget)
                case WidgetType.METRIC:
                    WidgetRenderer._render_metric_widget(widget)
                case WidgetType.CHART:
                    WidgetRenderer._render_chart_widget(widget)
                case WidgetType.TABLE:
                    WidgetRenderer._render_table_widget(widget)
                case WidgetType.BUTTON:
                    WidgetRenderer._render_button_widget(widget)
                case WidgetType.IMAGE:
                    WidgetRenderer._render_image_widget(widget)
                case WidgetType.CARD:
                    WidgetRenderer._render_card_widget(widget)
                case WidgetType.CUSTOM:
                    WidgetRenderer._render_custom_widget(widget)
                case _:
                    ui.label(f"Unknown widget type: {widget.type}")
    
    @staticmethod
    def _render_text_widget(widget: Widget):
        """Render a text widget"""
        config = widget.config
        content = config.get("content", "No content")
        
        if config.get("markdown", False):
            ui.markdown(content)
        else:
            ui.label(content).classes(config.get("classes", ""))
    
    @staticmethod
    def _render_metric_widget(widget: Widget):
        """Render a metric/KPI widget"""
        config = widget.config
        
        # Check if widget has a data source (stored separately, not in config)
        if widget.data_source:
            from app.data_source_service import DataSourceService
            data = DataSourceService.execute_widget_query(widget)
            if data and data.get("rows"):
                # Use first row's first value for metric
                row = data["rows"][0] if data["rows"] else {}
                if row:
                    # Get first numeric value
                    value = next((v for v in row.values() if isinstance(v, (int, float))), 0)
                    config["value"] = value
        
        with ui.column().classes("items-center justify-center"):
            if config.get("icon"):
                ui.icon(config["icon"], size="2rem")
            
            ui.label(config.get("title", "Metric")).classes("text-sm text-gray-600")
            ui.label(str(config.get("value", 0))).classes("text-3xl font-bold")
            
            if config.get("change"):
                change = config["change"]
                color = "text-green-600" if change > 0 else "text-red-600"
                ui.label(f"{'+' if change > 0 else ''}{change}%").classes(f"text-sm {color}")
    
    @staticmethod
    def _render_chart_widget(widget: Widget):
        """Render a chart widget"""
        config = widget.config
        chart_type = config.get("chart_type", "line")
        
        # Use Plotly for charts
        import plotly.graph_objects as go
        from nicegui import ui
        
        if config.get("title"):
            ui.label(config["title"]).classes("text-lg font-semibold mb-2")
        
        # Check if widget has a data source (stored separately, not in config)
        if widget.data_source:
            from app.data_source_service import DataSourceService
            query_data = DataSourceService.execute_widget_query(widget)
            if query_data and query_data.get("rows"):
                # Convert rows to chart data format
                rows = query_data["rows"]
                if rows:
                    # Get column names
                    cols = list(rows[0].keys()) if rows else []
                    # Use first column as x, second as y
                    if len(cols) >= 2:
                        data = {
                            "x": [row.get(cols[0]) for row in rows],
                            "y": [row.get(cols[1]) for row in rows]
                        }
                    elif len(cols) == 1:
                        # Single column - use index as x
                        data = {
                            "x": list(range(len(rows))),
                            "y": [row.get(cols[0]) for row in rows]
                        }
                    else:
                        data = {"x": ["No Data"], "y": [0]}
                else:
                    data = {"x": ["No Data"], "y": [0]}
            else:
                # No data from query
                data = {"x": ["No Data"], "y": [0]}
        else:
            # No data source configured - this should not happen with new widgets
            data = {"x": ["Configure Data Source"], "y": [0]}
        
        match chart_type:
            case "line":
                fig = go.Figure(data=go.Scatter(x=data.get("x", []), y=data.get("y", []), mode='lines+markers'))
            case "bar":
                fig = go.Figure(data=go.Bar(x=data.get("x", []), y=data.get("y", [])))
            case "pie":
                fig = go.Figure(data=go.Pie(labels=data.get("labels", data.get("x", [])), values=data.get("y", [])))
            case _:
                fig = go.Figure()
        
        fig.update_layout(
            height=config.get("height", 300),
            margin=dict(l=0, r=0, t=0, b=0),
            showlegend=config.get("show_legend", True)
        )
        
        ui.plotly(fig).classes("w-full")
    
    @staticmethod
    def _render_table_widget(widget: Widget):
        """Render a table widget"""
        config = widget.config
        
        if config.get("title"):
            ui.label(config["title"]).classes("text-lg font-semibold mb-2")
        
        # Check if widget has a data source (stored separately, not in config)
        if widget.data_source:
            from app.data_source_service import DataSourceService
            data = DataSourceService.execute_widget_query(widget)
            if data and data.get("rows"):
                rows = data["rows"]
                # Auto-generate columns from first row
                if rows:
                    columns = [
                        {"name": key, "label": key.replace("_", " ").title(), "field": key}
                        for key in rows[0].keys()
                    ]
                else:
                    columns = [{"name": "info", "label": "Info", "field": "info"}]
                    rows = [{"info": "No data available"}]
            else:
                columns = [{"name": "info", "label": "Info", "field": "info"}]
                rows = [{"info": "Query returned no results"}]
        else:
            # No data source configured - show message
            columns = [{"name": "message", "label": "Message", "field": "message"}]
            rows = [{"message": "Please configure a data source for this widget"}]
        
        ui.table(columns=columns, rows=rows).classes("w-full")
    
    @staticmethod
    def _render_button_widget(widget: Widget):
        """Render a button widget"""
        config = widget.config
        
        def handle_click():
            action = config.get("action", "notify")
            if action == "notify":
                ui.notify(config.get("message", "Button clicked!"))
            elif action == "navigate":
                ui.navigate.to(config.get("url", "/"))
            # Add more actions as needed
        
        ui.button(
            config.get("label", "Click Me"),
            on_click=handle_click,
            icon=config.get("icon")
        ).props(config.get("props", ""))
    
    @staticmethod
    def _render_image_widget(widget: Widget):
        """Render an image widget"""
        config = widget.config
        
        if config.get("title"):
            ui.label(config["title"]).classes("text-lg font-semibold mb-2")
        
        ui.image(config.get("source", "https://via.placeholder.com/300")).classes(
            config.get("classes", "w-full")
        )
        
        if config.get("caption"):
            ui.label(config["caption"]).classes("text-sm text-gray-600 mt-2")
    
    @staticmethod
    def _render_card_widget(widget: Widget):
        """Render a card widget with custom content"""
        config = widget.config
        
        if config.get("title"):
            ui.label(config["title"]).classes("text-lg font-semibold mb-2")
        
        if config.get("subtitle"):
            ui.label(config["subtitle"]).classes("text-sm text-gray-600 mb-2")
        
        if config.get("content"):
            ui.html(config["content"])
        
        if config.get("actions"):
            with ui.row().classes("mt-4 gap-2"):
                for action in config["actions"]:
                    ui.button(action.get("label", "Action")).props("flat")
    
    @staticmethod
    def _render_custom_widget(widget: Widget):
        """Render a custom widget with raw HTML/JavaScript"""
        config = widget.config
        
        if config.get("html"):
            ui.html(config["html"])
        
        if config.get("javascript"):
            ui.run_javascript(config["javascript"])
        
        if config.get("component"):
            # For advanced custom components
            ui.label("Custom component placeholder").classes("text-gray-500")


class WidgetGrid:
    """Manages the grid layout of widgets"""
    
    def __init__(self, columns: int = 12):
        self.columns = columns
        self.container = None
        self.on_edit = None
        self.on_delete = None
    
    def render(self, widgets: list[Widget], editable: bool = False):
        """Render all widgets in a grid layout"""
        # Group widgets by row based on their size
        current_row = []
        current_width = 0
        
        for widget in sorted(widgets, key=lambda w: w.position):
            widget_width = self._get_widget_width(widget.size)
            
            if current_width + widget_width > self.columns:
                # Render current row
                self._render_row(current_row, editable)
                current_row = [widget]
                current_width = widget_width
            else:
                current_row.append(widget)
                current_width += widget_width
        
        # Render last row
        if current_row:
            self._render_row(current_row, editable)
    
    def _get_widget_width(self, size: WidgetSize) -> int:
        """Get widget width in grid columns"""
        width_map = {
            WidgetSize.SMALL: 3,
            WidgetSize.MEDIUM: 6,
            WidgetSize.LARGE: 9,
            WidgetSize.FULL: 12
        }
        return width_map.get(size, 6)
    
    def _render_row(self, widgets: list[Widget], editable: bool):
        """Render a row of widgets"""
        with ui.row().classes("w-full gap-4"):
            for widget in widgets:
                WidgetRenderer.render_widget(
                    widget,
                    on_edit=self.on_edit if editable else None,
                    on_delete=self.on_delete if editable else None
                )
    
    def set_callbacks(self, on_edit=None, on_delete=None):
        """Set callbacks for edit and delete actions"""
        self.on_edit = on_edit
        self.on_delete = on_delete