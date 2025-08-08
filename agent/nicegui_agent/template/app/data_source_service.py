"""Service for managing data sources and database introspection"""
import logging
from typing import List, Dict, Any, Optional
from sqlmodel import text
from app.database import engine
from app.widget_models import Widget

logger = logging.getLogger(__name__)


class DataSourceService:
    """Service for managing data sources for widgets"""
    
    @staticmethod
    def get_available_tables() -> List[Dict[str, Any]]:
        """Get all available tables in the database with their columns"""
        tables = []
        
        with engine.connect() as conn:
            # Get all tables
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """))
            
            for row in result:
                table_name = row[0]
                
                # Get columns for each table
                col_result = conn.execute(text("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    AND table_name = :table_name
                    ORDER BY ordinal_position
                """), {"table_name": table_name})
                
                columns = []
                for col_row in col_result:
                    columns.append({
                        "name": col_row[0],
                        "type": col_row[1],
                        "nullable": col_row[2] == 'YES'
                    })
                
                # Get row count
                try:
                    count_result = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
                    row_count = count_result.scalar()
                except Exception as e:
                    logger.warning(f"Failed to get row count for {table_name}: {e}")
                    row_count = 0
                
                tables.append({
                    "name": table_name,
                    "columns": columns,
                    "row_count": row_count
                })
        
        logger.info(f"Found {len(tables)} tables in database")
        return tables
    
    @staticmethod
    def get_table_data(table_name: str, limit: int = 100, 
                       columns: Optional[List[str]] = None,
                       order_by: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get data from a specific table"""
        
        # Validate table name to prevent SQL injection
        available_tables = DataSourceService.get_available_tables()
        if not any(t["name"] == table_name for t in available_tables):
            logger.error(f"Table {table_name} not found")
            return []
        
        with engine.connect() as conn:
            # Build column list
            if columns:
                # Validate column names
                table_info = next((t for t in available_tables if t["name"] == table_name), None)
                if table_info:
                    valid_cols = [c["name"] for c in table_info["columns"]]
                    columns = [c for c in columns if c in valid_cols]
                    col_str = ", ".join([f'"{c}"' for c in columns])
                else:
                    col_str = "*"
            else:
                col_str = "*"
            
            # Build query
            query = f'SELECT {col_str} FROM "{table_name}"'
            
            if order_by:
                # Validate order_by column
                query += f' ORDER BY "{order_by}"'
            
            query += f" LIMIT {limit}"
            
            try:
                result = conn.execute(text(query))
                rows = []
                for row in result:
                    rows.append(dict(row._mapping))
                
                logger.info(f"Retrieved {len(rows)} rows from {table_name}")
                return rows
            except Exception as e:
                logger.error(f"Error fetching data from {table_name}: {e}")
                return []
    
    @staticmethod
    def get_aggregated_data(table_name: str, 
                           aggregation_type: str = "count",
                           group_by: Optional[str] = None,
                           value_column: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get aggregated data from a table"""
        
        # Validate table
        available_tables = DataSourceService.get_available_tables()
        if not any(t["name"] == table_name for t in available_tables):
            return []
        
        with engine.connect() as conn:
            try:
                if aggregation_type == "count" and group_by:
                    query = f'''
                        SELECT "{group_by}" as label, COUNT(*) as value
                        FROM "{table_name}"
                        GROUP BY "{group_by}"
                        ORDER BY value DESC
                        LIMIT 10
                    '''
                elif aggregation_type == "sum" and group_by and value_column:
                    query = f'''
                        SELECT "{group_by}" as label, SUM("{value_column}") as value
                        FROM "{table_name}"
                        GROUP BY "{group_by}"
                        ORDER BY value DESC
                        LIMIT 10
                    '''
                elif aggregation_type == "avg" and group_by and value_column:
                    query = f'''
                        SELECT "{group_by}" as label, AVG("{value_column}") as value
                        FROM "{table_name}"
                        GROUP BY "{group_by}"
                        ORDER BY value DESC
                        LIMIT 10
                    '''
                else:
                    # Simple count
                    query = f'SELECT COUNT(*) as value FROM "{table_name}"'
                
                result = conn.execute(text(query))
                rows = []
                for row in result:
                    rows.append(dict(row._mapping))
                
                return rows
            except Exception as e:
                logger.error(f"Error aggregating data from {table_name}: {e}")
                return []
    
    @staticmethod
    def execute_widget_query(widget: Widget) -> Dict[str, Any]:
        """Execute the query configured for a widget and return data"""
        
        # Check for data_source in widget directly first, then fall back to config
        data_source = widget.data_source if widget.data_source else widget.config.get("data_source", {})
        
        if not data_source:
            return {}
        
        source_type = data_source.get("type", "static")
        
        match source_type:
            case "table":
                # Direct table data
                table_name = data_source.get("table")
                columns = data_source.get("columns", [])
                limit = data_source.get("limit", 100)
                order_by = data_source.get("order_by")
                
                if table_name:
                    rows = DataSourceService.get_table_data(
                        table_name, limit=limit, 
                        columns=columns, order_by=order_by
                    )
                    return {"rows": rows}
            
            case "aggregation":
                # Aggregated data
                table_name = data_source.get("table")
                agg_type = data_source.get("aggregation", "count")
                group_by = data_source.get("group_by")
                value_column = data_source.get("value_column")
                
                if table_name:
                    rows = DataSourceService.get_aggregated_data(
                        table_name, agg_type, group_by, value_column
                    )
                    
                    # Format for charts
                    if widget.type.value == "chart":
                        labels = [r.get("label", "") for r in rows]
                        values = [r.get("value", 0) for r in rows]
                        return {"x": labels, "y": values}
                    else:
                        return {"rows": rows}
            
            case "query" | "custom_sql":
                # SQL query (be very careful with this!)
                query = data_source.get("query", "")
                if query and "DROP" not in query.upper() and "DELETE" not in query.upper():
                    try:
                        with engine.connect() as conn:
                            result = conn.execute(text(query))
                            rows = [dict(row._mapping) for row in result]
                            
                            # For metric widgets, return single value
                            if widget.type.value == "metric" and rows:
                                return {"value": rows[0].get(list(rows[0].keys())[0], 0), "rows": rows}
                            
                            return {"rows": rows, "success": True}
                    except Exception as e:
                        logger.error(f"Error executing query: {e}")
                        return {"error": str(e), "success": False}
        
        return {}