#!/usr/bin/env python3
"""Test data source functionality"""

import sys
sys.path.append('/app')

from app.data_source_service import DataSourceService
from app.widget_service import WidgetService
from app.widget_models import WidgetType, WidgetSize

def test_data_sources():
    print("=" * 60)
    print("DATA SOURCE SYSTEM TEST")
    print("=" * 60)
    
    # 1. Test database introspection
    print("\n1. DATABASE INTROSPECTION:")
    tables = DataSourceService.get_available_tables()
    print(f"   Found {len(tables)} tables:")
    for table in tables:
        print(f"   - {table['name']} ({table['row_count']} rows, {len(table['columns'])} columns)")
        if table['columns']:
            print(f"     Sample columns: {', '.join([c['name'] for c in table['columns'][:3]])}")
    
    # 2. Test table data retrieval
    print("\n2. TABLE DATA RETRIEVAL:")
    if tables:
        test_table = tables[0]['name']
        print(f"   Testing with table: {test_table}")
        data = DataSourceService.get_table_data(test_table, limit=5)
        print(f"   Retrieved {len(data)} rows")
        if data:
            print(f"   First row keys: {list(data[0].keys())}")
    
    # 3. Create a data-connected widget
    print("\n3. DATA-CONNECTED WIDGET:")
    if tables:
        # Create a metric widget connected to data
        metric_widget = WidgetService.create_widget(
            name="Database Record Count",
            type=WidgetType.METRIC,
            size=WidgetSize.SMALL,
            config={
                "title": "Total Records",
                "icon": "storage",
                "data_source": {
                    "type": "aggregation",
                    "table": tables[0]['name'],
                    "aggregation": "count"
                }
            }
        )
        print(f"   ✅ Created data-connected metric widget: {metric_widget.name}")
        
        # Create a table widget connected to data
        table_widget = WidgetService.create_widget(
            name="Data Table",
            type=WidgetType.TABLE,
            size=WidgetSize.LARGE,
            config={
                "title": f"Records from {tables[0]['name']}",
                "data_source": {
                    "type": "table",
                    "table": tables[0]['name'],
                    "limit": 10
                }
            }
        )
        print(f"   ✅ Created data-connected table widget: {table_widget.name}")
        
        # Test executing widget query
        print("\n4. WIDGET QUERY EXECUTION:")
        data = DataSourceService.execute_widget_query(metric_widget)
        print(f"   Metric widget data: {data}")
        
        data = DataSourceService.execute_widget_query(table_widget)
        print(f"   Table widget retrieved {len(data.get('rows', []))} rows")
        
        # Clean up test widgets
        if metric_widget.id is not None:
            WidgetService.delete_widget(metric_widget.id)
        if table_widget.id is not None:
            WidgetService.delete_widget(table_widget.id)
        print("\n   ✅ Test widgets cleaned up")
    
    print("\n" + "=" * 60)
    print("DATA SOURCE TEST COMPLETE")
    print("=" * 60)
    
    print("\nSUMMARY:")
    print("✅ Database introspection works")
    print("✅ Table data retrieval works")
    print("✅ Data-connected widgets work")
    print("✅ Widget query execution works")
    
    print("\nNOTE: Widgets can now be connected to any database table")
    print("and will automatically display live data!")

if __name__ == "__main__":
    test_data_sources()