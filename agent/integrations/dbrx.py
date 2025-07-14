import re
from dataclasses import dataclass
from typing import List, Optional
import polars as pl
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState, State
from functools import lru_cache

from log import get_logger

logger = get_logger(__name__)


@dataclass
class TableMetadata:
    catalog: str
    schema: str
    name: str
    full_name: str
    table_type: str
    owner: Optional[str] = None
    comment: Optional[str] = None
    storage_location: Optional[str] = None
    data_source_format: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class ColumnMetadata:
    name: str
    data_type: str
    comment: Optional[str] = None
    nullable: Optional[bool] = None
    position: Optional[int] = None


@dataclass
class TableDetails:
    metadata: TableMetadata
    columns: List[ColumnMetadata]
    sample_data: Optional[pl.DataFrame] = None
    row_count: Optional[int] = None
    size_bytes: Optional[int] = None


class DatabricksClient:

    def __init__(self, workspace_client: Optional[WorkspaceClient] = None):
        self.client = workspace_client or WorkspaceClient()
        logger.info("Initialized Databricks client")

    def _get_warehouse_id(self) -> str:
        """Get an available warehouse ID, preferring running warehouses."""
        running_warehouses = [x for x in self.client.warehouses.list() if x.state == State.RUNNING]
        if not running_warehouses:
            warehouses = list(self.client.warehouses.list())
            if not warehouses:
                raise RuntimeError("No warehouses available")
            warehouse = warehouses[0]
        else:
            warehouse = running_warehouses[0]
        if not warehouse.id:
            raise RuntimeError("Warehouse has no ID")
        return warehouse.id

    @lru_cache(maxsize=128)
    def list_tables(
        self,
        catalog: str = "samples",
        schema: str = "*",
        exclude_inaccessible: bool = True
    ) -> List[TableMetadata]:
        logger.info(f"Listing tables: catalog={catalog}, schema={schema}, exclude_inaccessible={exclude_inaccessible}")

        tables = []

        # Get list of catalogs
        if catalog == "*":
            catalogs = list(self.client.catalogs.list())
            catalog_names = [c.name for c in catalogs]
            logger.debug(f"Found {len(catalog_names)} catalogs")
        else:
            catalog_names = [catalog]

        # Iterate through catalogs
        for catalog_name in catalog_names:
            if not catalog_name:
                continue
            # Get list of schemas
            if schema == "*":
                schemas = list(self.client.schemas.list(catalog_name=catalog_name))
                schema_names = [s.name for s in schemas if s.name]
                logger.debug(f"Found {len(schema_names)} schemas in catalog {catalog_name}")
            else:
                schema_names = [schema]

            # Iterate through schemas
            for schema_name in schema_names:
                if not schema_name:
                    continue
                # List tables in schema
                table_list = list(self.client.tables.list(
                    catalog_name=catalog_name,
                    schema_name=schema_name
                ))
                logger.debug(f"Found {len(table_list)} tables in {catalog_name}.{schema_name}")

                for table in table_list:
                    # Skip if exclude_inaccessible is True and we can't access
                    if exclude_inaccessible and table.full_name and not self._has_table_access(table.full_name):
                        logger.debug(f"Skipping inaccessible table: {table.full_name}")
                        continue

                    # Skip tables with missing required fields
                    if not all([table.name, table.full_name, catalog_name, schema_name]):
                        logger.debug(f"Skipping table with missing required fields")
                        continue

                    tables.append(TableMetadata(
                        catalog=catalog_name,
                        schema=schema_name,
                        name=table.name,  # type: ignore
                        full_name=table.full_name,  # type: ignore
                        table_type=table.table_type.value if table.table_type else "UNKNOWN",
                        owner=table.owner,
                        comment=None,  # don't include comment in list_tables
                        storage_location=table.storage_location,
                        data_source_format=table.data_source_format.value if table.data_source_format else None,
                        created_at=str(table.created_at) if table.created_at else None,
                        updated_at=str(table.updated_at) if table.updated_at else None
                    ))

        logger.info(f"Found {len(tables)} accessible tables")
        return tables

    @lru_cache(maxsize=128)
    def get_table_details(self, table_full_name: str, sample_size: int = 10) -> TableDetails:
        logger.info(f"Getting details for table: {table_full_name}")

        # Parse table metadata
        parts = table_full_name.split(".")
        if len(parts) != 3:
            raise ValueError(f"Invalid table name format: {table_full_name}. Expected catalog.schema.table")

        # Get table metadata
        table = self.client.tables.get(table_full_name)

        metadata = TableMetadata(
            catalog=parts[0],
            schema=parts[1],
            name=parts[2],
            full_name=table_full_name,
            table_type=table.table_type.value if table.table_type else "UNKNOWN",
            owner=table.owner,
            comment=table.comment,
            storage_location=table.storage_location,
            data_source_format=table.data_source_format.value if table.data_source_format else None,
            created_at=str(table.created_at) if table.created_at else None,
            updated_at=str(table.updated_at) if table.updated_at else None
        )

        # Parse columns
        columns = []
        if table.columns:
            for i, col in enumerate(table.columns):
                if col.name and col.type_name:
                    columns.append(ColumnMetadata(
                        name=col.name,
                        data_type=str(col.type_name),
                        comment=col.comment,
                        nullable=col.nullable,
                        position=i
                    ))

        # Get sample data
        sample_data = None
        row_count = None

        # Execute sample query
        sample_query = f"SELECT * FROM {table_full_name} LIMIT {sample_size}"
        logger.debug(f"Executing sample query: {sample_query}")

        warehouse_id = self._get_warehouse_id()

        execution = self.client.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=sample_query,
            wait_timeout="30s"
        )

        if execution.status and execution.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"Sample query failed with state: {execution.status.state}")

        # Convert result to polars DataFrame
        if execution.result and execution.result.data_array and execution.manifest and execution.manifest.schema and execution.manifest.schema.columns:
            col_names = [col.name for col in execution.manifest.schema.columns if col.name]
            sample_data = pl.DataFrame(execution.result.data_array, schema=col_names, orient="row")
            logger.debug(f"Retrieved {len(sample_data)} sample rows")

        # Get row count
        count_query = f"SELECT COUNT(*) as count FROM {table_full_name}"
        execution = self.client.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=count_query,
            wait_timeout="30s"
        )

        if execution.status and execution.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"Count query failed with state: {execution.status.state}")

        if execution.result and execution.result.data_array:
            if execution.result.data_array:
                row_count = int(execution.result.data_array[0][0])
                logger.debug(f"Table has {row_count} rows")
            else:
                raise RuntimeError("Count query returned no results")
        else:
            raise RuntimeError("Count query returned no results")

        return TableDetails(
            metadata=metadata,
            columns=columns,
            sample_data=sample_data,
            row_count=row_count
        )

    def _has_table_access(self, table_full_name: str) -> bool:
        try:
            # Try to get table info - this will fail if no access
            self.client.tables.get(table_full_name)
            return True
        except Exception:
            return False

    def _is_read_only_query(self, query: str) -> bool:
        """Check if query is read-only by parsing for write operations."""
        # normalize query - remove comments and extra whitespace
        query_clean = re.sub(r'/\*.*?\*/', '', query, flags=re.DOTALL)  # remove /* */ comments
        query_clean = re.sub(r'--.*', '', query_clean)  # remove -- comments
        query_clean = re.sub(r'\s+', ' ', query_clean.strip()).upper()

        # check for write operations (more comprehensive than prefix matching)
        write_keywords = {
            'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER',
            'TRUNCATE', 'REPLACE', 'MERGE', 'COPY', 'GRANT', 'REVOKE',
            'SET', 'USE', 'CALL'  # procedures/functions that might modify state
        }

        # split into tokens and check if any write keyword appears in statement context
        tokens = query_clean.split()
        if not tokens:
            return False

        # check main statement keywords (not in subqueries/CTEs)
        for token in tokens:
            if token in write_keywords:
                return False

        return True

    @lru_cache(maxsize=128)
    def execute_query(self, query: str, timeout: int = 45) -> pl.DataFrame:
        """Execute a SELECT query and return results as a polars DataFrame.

        Args:
            query: SQL query to execute (must be a SELECT statement)
            timeout: Query execution timeout in seconds (default: 45s)

        Returns:
            polars DataFrame with query results

        Raises:
            ValueError: If query is not a SELECT statement
            RuntimeError: If no warehouses available or query execution fails
        """

        timeout = min(timeout, 50)
        timeout_str = f"{timeout}s"

        # validate it's a read-only query for safety
        if not self._is_read_only_query(query):
            raise ValueError("Only SELECT queries are allowed")
        logger.info(f"Executing query: {query.replace('\n', ' ')}..., timeout {timeout}")

        # get available warehouse
        warehouse_id = self._get_warehouse_id()
        logger.debug(f"Using warehouse: {warehouse_id}")

        # execute the query
        execution = self.client.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=query,
            wait_timeout=timeout_str
        )

        if execution.status and execution.status.state != StatementState.SUCCEEDED:
            error_msg = f"Query failed with state: {execution.status.state}"
            if execution.status.error:
                error_msg += f" - {execution.status.error.message}"
            raise RuntimeError(error_msg)

        # convert result to polars DataFrame
        if execution.manifest and execution.manifest.schema and execution.manifest.schema.columns:
            col_names = [col.name for col in execution.manifest.schema.columns if col.name]

            if execution.result and execution.result.data_array:
                df = pl.DataFrame(execution.result.data_array, schema=col_names, orient="row")
                logger.info(f"Query returned {len(df)} rows with {len(df.columns)} columns")
                return df
            else:
                # return empty DataFrame with schema preserved
                logger.info("Query returned no results, preserving schema")
                # create empty dataframe with correct schema
                schema = {col.name: pl.Utf8 for col in execution.manifest.schema.columns if col.name}
                return pl.DataFrame(schema=schema)
        else:
            # return empty DataFrame if no schema available
            logger.info("Query returned no results and no schema")
            return pl.DataFrame()


if __name__ == "__main__":
    # Example usage
    client = DatabricksClient()
    try:
        tables = client.list_tables()
        for table in tables:
            print(f"Table: {table.full_name}, Type: {table.table_type}")
            details = client.get_table_details(table.full_name)
            print(f"Columns: {[col.name for col in details.columns]}")
            if details.sample_data is not None:
                print(f"Sample data:\n{details.sample_data.head()}")
    except Exception as e:
        logger.error(f"Error: {e}")
