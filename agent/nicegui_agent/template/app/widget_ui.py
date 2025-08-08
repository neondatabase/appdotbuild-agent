"""UI for managing widgets"""

import logging
from typing import Optional
from nicegui import ui
from app.widget_service import WidgetService
from app.widget_renderer import WidgetGrid
from app.widget_models import Widget, WidgetType, WidgetSize

logger = logging.getLogger(__name__)


class WidgetManager:
    """UI component for managing widgets"""

    def __init__(self):
        self.widget_service = WidgetService()
        self.grid = WidgetGrid()
        self.edit_mode = False
        self.current_page = "dashboard"
        self.container = None

    def render_dashboard(self):
        """Render the main dashboard with widgets"""
        with ui.column().classes("w-full") as self.container:
            # Header with controls
            with ui.row().classes("w-full justify-between items-center mb-6"):
                ui.label("Dashboard").classes("text-2xl font-bold")

                with ui.row().classes("gap-2"):
                    ui.button(
                        "Edit Mode" if not self.edit_mode else "View Mode",
                        icon="edit" if not self.edit_mode else "visibility",
                        on_click=self.toggle_edit_mode,
                    ).props("outline")

                    ui.button("Add Widget", icon="add", on_click=self.show_add_widget_dialog).props("color=primary")

            # Create widget container
            with ui.column().classes("w-full") as self.widget_container:
                pass

            # Render widgets
            self.refresh_widgets()

    def refresh_widgets(self):
        """Refresh the widget display"""
        if hasattr(self, "widget_container"):
            self.widget_container.clear()

            with self.widget_container:
                widgets = self.widget_service.get_widgets_for_page(self.current_page)

                if not widgets:
                    with ui.card().classes("w-full p-8 text-center"):
                        ui.icon("dashboard", size="4rem").classes("text-gray-400")
                        ui.label("No widgets yet").classes("text-xl text-gray-600 mt-4")
                        ui.label("Click 'Add Widget' to get started").classes("text-gray-500")
                else:
                    # Set callbacks for edit and delete
                    self.grid.set_callbacks(on_edit=self.edit_widget, on_delete=self.delete_widget)
                    self.grid.render(widgets, editable=self.edit_mode)

    def toggle_edit_mode(self):
        """Toggle between edit and view mode"""
        self.edit_mode = not self.edit_mode
        ui.notify(f"{'Edit' if self.edit_mode else 'View'} mode activated")
        self.refresh_widgets()

    def show_add_widget_dialog(self, on_close=None):
        """Show dialog for adding a new widget"""
        def handle_close():
            dialog.close()
            if on_close:
                on_close()
        
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label("Add New Widget").classes("text-xl font-bold mb-4")

            # Widget configuration form
            name_input = ui.input("Widget Name", placeholder="Enter widget name")

            type_select = ui.select(
                label="Widget Type",
                options={
                    WidgetType.TEXT: "Text",
                    WidgetType.METRIC: "Metric/KPI",
                    WidgetType.CHART: "Chart",
                    WidgetType.TABLE: "Table",
                    WidgetType.BUTTON: "Button",
                    WidgetType.IMAGE: "Image",
                    WidgetType.CARD: "Card",
                },
                value=WidgetType.TEXT,
            )

            size_select = ui.select(
                label="Widget Size",
                options={
                    WidgetSize.SMALL: "Small (25%)",
                    WidgetSize.MEDIUM: "Medium (50%)",
                    WidgetSize.LARGE: "Large (75%)",
                    WidgetSize.FULL: "Full Width (100%)",
                },
                value=WidgetSize.MEDIUM,
            )

            # Data source configuration (REQUIRED)
            ui.label("Data Source (Required)").classes("text-sm font-medium text-gray-700 mt-4 mb-2")
            ui.label("⚠️ Widgets must connect to real data sources").classes("text-xs text-amber-600 mb-2")

            from app.data_source_service import DataSourceService

            tables = DataSourceService.get_available_tables()
            table_options = {}
            for table in tables:
                table_options[table["name"]] = f"{table['name']} ({table['row_count']} rows)"
            
            # Add query option
            table_options["custom_query"] = "📝 Custom SQL Query"

            default_table = list(table_options.keys())[0] if table_options else None
            data_source_select = ui.select(
                label="Select Data Source", 
                options=table_options, 
                value=default_table
            ).classes("w-full").props("outlined filled")

            # Dynamic data source configuration
            data_config_container = ui.column().classes("w-full mt-2")
            
            # Store query input reference
            query_input_ref = {"element": None}

            def update_data_config():
                data_config_container.clear()
                with data_config_container:
                    if data_source_select.value == "custom_query":
                        ui.label("Enter SQL Query:").classes("text-sm font-medium")
                        query_input_ref["element"] = ui.textarea(
                            placeholder="SELECT * FROM table WHERE condition",
                            value=""
                        ).classes("w-full font-mono text-sm").props("rows=3")
                        ui.label("💡 Query will be executed against the database").classes("text-xs text-gray-500")
                    elif data_source_select.value:
                        selected_table = next((t for t in tables if t["name"] == data_source_select.value), None)
                        if selected_table:
                            ui.label(f"Table: {selected_table['name']}").classes("text-sm font-medium")
                            ui.label(f"Columns available:").classes("text-xs text-gray-600 mt-1")
                            for col in selected_table["columns"][:8]:  # Show first 8 columns
                                ui.label(f"  • {col['name']} ({col['type']})").classes("text-xs text-gray-600")
                            if len(selected_table["columns"]) > 8:
                                ui.label(f"  ... and {len(selected_table['columns']) - 8} more").classes("text-xs text-gray-400")

            data_source_select.on("update:model-value", update_data_config)
            update_data_config()  # Show initial data config

            # Dynamic configuration based on widget type
            ui.label("Widget Configuration").classes("text-sm font-medium text-gray-700 mt-4 mb-2")
            config_container = ui.column().classes("w-full")

            def update_config_fields():
                config_container.clear()
                with config_container:
                    widget_type = type_select.value

                    match widget_type:
                        case WidgetType.TEXT:
                            ui.textarea("Content", placeholder="Enter text or markdown")
                            ui.switch("Enable Markdown")

                        case WidgetType.METRIC:
                            ui.input("Title", placeholder="Metric title")
                            ui.number("Value", value=0)
                            ui.input("Icon", placeholder="Icon name (optional)")
                            ui.number("Change %", placeholder="Change percentage")

                        case WidgetType.CHART:
                            ui.select(label="Chart Type", options=["line", "bar", "pie"], value="line")
                            ui.input("Title", placeholder="Chart title")
                            ui.switch("Show Legend")

                        case WidgetType.BUTTON:
                            ui.input("Label", placeholder="Button text")
                            ui.input("Icon", placeholder="Icon name (optional)")
                            ui.select(label="Action", options=["notify", "navigate"], value="notify")

                        case WidgetType.IMAGE:
                            ui.input("Image URL", placeholder="https://...")
                            ui.input("Caption", placeholder="Image caption (optional)")

            type_select.on("update:model-value", update_config_fields)
            update_config_fields()

            # Action buttons
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Cancel", on_click=handle_close).props("flat")
                ui.button(
                    "Add Widget",
                    on_click=lambda: self.add_widget(
                        name_input.value,
                        type_select.value,
                        size_select.value,
                        dialog,
                        data_source=data_source_select.value,
                        query_text=query_input_ref["element"].value if query_input_ref["element"] else None,
                        on_close=on_close,
                    ),
                ).props("color=primary")

        dialog.open()

    def add_widget(
        self,
        name: str,
        widget_type: Optional[WidgetType],
        size: Optional[WidgetSize],
        dialog,
        data_source=None,
        query_text=None,
        data_config=None,
        on_close=None,
    ):
        """Add a new widget"""
        if not name:
            ui.notify("Please enter a widget name", type="warning")
            return

        if not widget_type:
            ui.notify("Please select a widget type", type="warning")
            return

        if not size:
            size = WidgetSize.MEDIUM  # Default size

        # Create widget with basic config
        config = self.get_default_config(widget_type)

        # Prepare data source configuration (REQUIRED)
        data_source_config = None
        if data_source == "custom_query":
            # Use the query text if provided
            if query_text:
                data_source_config = {
                    "type": "query",
                    "query": query_text,
                    "refresh_interval": 60,
                }
            else:
                # Fallback to default query
                from app.data_source_service import DataSourceService
                tables = DataSourceService.get_available_tables()
                default_table = tables[0]['name'] if tables else 'widget'
                data_source_config = {
                    "type": "query",
                    "query": f"SELECT * FROM {default_table} LIMIT 10",
                    "refresh_interval": 60,
                }
        elif data_source:
            data_source_config = {
                "type": "table",
                "table": data_source,
                "columns": data_config.get("columns", []) if data_config else [],
                "limit": data_config.get("limit", 100) if data_config else 100,
            }
        else:
            # No data source selected - this should not happen with new UI
            ui.notify("Please select a data source", type="warning")
            return

        self.widget_service.create_widget(
            name=name, 
            type=widget_type, 
            size=size, 
            page=self.current_page, 
            config=config,
            data_source=data_source_config
        )

        ui.notify(f"Widget '{name}' added successfully", type="positive")
        dialog.close()
        if on_close:
            on_close()
        else:
            self.refresh_widgets()

    def get_default_config(self, widget_type: WidgetType) -> dict:
        """Get default configuration for a widget type"""
        configs = {
            WidgetType.TEXT: {"content": "New text widget. Data will be loaded from the selected source.", "markdown": False},
            WidgetType.METRIC: {"title": "New Metric", "icon": "trending_up"},
            WidgetType.CHART: {
                "chart_type": "line",
                "title": "Data Chart",
                # Data will come from data_source
            },
            WidgetType.TABLE: {
                "title": "Data Table",
                # Columns and rows will come from data_source
            },
            WidgetType.BUTTON: {"label": "Click Me", "action": "notify", "message": "Button clicked!"},
            WidgetType.IMAGE: {"source": "https://via.placeholder.com/400x200", "caption": "Sample Image"},
            WidgetType.CARD: {
                "title": "Card Title",
                "subtitle": "Card subtitle",
                "content": "<p>Card content goes here</p>",
            },
        }
        return configs.get(widget_type, {})

    def edit_widget(self, widget: Widget, on_close=None):
        """Edit an existing widget"""
        def handle_close():
            dialog.close()
            if on_close:
                on_close()
        
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label(f"Edit Widget: {widget.name}").classes("text-xl font-bold mb-4")

            name_input = ui.input("Widget Name", value=widget.name)

            size_select = ui.select(
                label="Widget Size",
                options={
                    WidgetSize.SMALL: "Small (25%)",
                    WidgetSize.MEDIUM: "Medium (50%)",
                    WidgetSize.LARGE: "Large (75%)",
                    WidgetSize.FULL: "Full Width (100%)",
                },
                value=widget.size,
            )

            # Show current data source
            ui.label("Data Source").classes("mt-4 text-sm font-medium text-gray-700")
            if widget.data_source:
                with ui.card().classes("w-full p-3 bg-blue-50"):
                    source_type = widget.data_source.get("type", "unknown")
                    if source_type == "query":
                        ui.label("📝 Custom Query").classes("text-sm font-medium")
                        ui.label(widget.data_source.get("query", "")).classes("text-xs font-mono text-gray-600")
                    elif source_type == "table":
                        ui.label(f"📊 Table: {widget.data_source.get('table', 'unknown')}").classes("text-sm font-medium")
                    elif source_type == "aggregation":
                        ui.label(f"📈 Aggregation from: {widget.data_source.get('table', 'unknown')}").classes("text-sm font-medium")
            else:
                ui.label("⚠️ No data source configured").classes("text-sm text-amber-600")

            # Config editor (simplified - in production, use dynamic forms)
            import json

            ui.label("Configuration (JSON)").classes("mt-4")
            config_editor = ui.textarea(
                value=json.dumps(widget.config, indent=2), placeholder="Widget configuration"
            ).classes("w-full font-mono text-sm")

            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Cancel", on_click=handle_close).props("flat")
                ui.button("Delete", on_click=lambda: self.delete_widget(widget, dialog, on_close)).props("flat color=negative")
                ui.button(
                    "Save",
                    on_click=lambda: self.save_widget_changes(
                        widget, name_input.value, size_select.value, config_editor.value, dialog, on_close
                    ),
                ).props("color=primary")

        dialog.open()

    def save_widget_changes(self, widget: Widget, name: str, size: Optional[WidgetSize], config_str: str, dialog, on_close=None):
        """Save changes to a widget"""
        import json

        try:
            config = json.loads(config_str) if config_str else {}
        except (json.JSONDecodeError, ValueError):
            config = widget.config
            logger.warning(f"Failed to parse config JSON for widget {widget.id}, using existing config")

        if not size:
            size = widget.size  # Keep existing size if not provided

        if widget.id is not None:
            self.widget_service.update_widget(widget.id, name=name, size=size, config=config)
        else:
            logger.error(f"Cannot update widget without ID: {widget.name}")

        ui.notify(f"Widget '{name}' updated", type="positive")
        dialog.close()
        if on_close:
            on_close()
        else:
            self.refresh_widgets()

    def delete_widget(self, widget: Widget, dialog=None, on_close=None):
        """Delete a widget with confirmation"""

        def confirm_delete():
            # Delete from database
            if widget.id is not None:
                success = self.widget_service.delete_widget(widget.id)
            else:
                success = False
            if success:
                ui.notify(f"Widget '{widget.name}' deleted", type="positive")
                if dialog:
                    dialog.close()
                confirm_dialog.close()
                # Call the on_close callback or refresh widgets
                if on_close:
                    on_close()
                else:
                    self.refresh_widgets()
            else:
                ui.notify(f"Failed to delete widget '{widget.name}'", type="negative")

        with ui.dialog() as confirm_dialog, ui.card():
            ui.label(f"Delete '{widget.name}'?").classes("text-lg")
            ui.label("This action cannot be undone.").classes("text-gray-600")

            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Cancel", on_click=confirm_dialog.close).props("flat")
                ui.button("Delete", on_click=confirm_delete).props("color=negative")

        confirm_dialog.open()


# Page route for widget dashboard
@ui.page("/widgets")
def widgets_page():
    """Widgets management page"""
    manager = WidgetManager()
    manager.render_dashboard()


# Initialize widgets on startup
def initialize_widgets():
    """Initialize widget system on app startup"""
    try:
        WidgetService.initialize_default_widgets()
        logger.info("Widget system initialized")
    except Exception as e:
        logger.error(f"Failed to initialize widgets: {e}")
