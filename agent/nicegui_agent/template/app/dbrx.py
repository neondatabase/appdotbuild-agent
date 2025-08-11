from typing import List, Dict, Any, ClassVar, Sequence, TypeVar
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState, State

from pydantic import BaseModel
from logging import getLogger

logger = getLogger(__name__)

T = TypeVar("T", bound="DatabricksModel")


def execute_databricks_query(query: str) -> List[Dict[str, Any]]:
    """helper function to execute SQL query via WorkspaceClient"""
    import os
    
    # Check if credentials are configured
    if not os.getenv("DATABRICKS_HOST") or not os.getenv("DATABRICKS_TOKEN"):
        logger.warning("Databricks credentials not configured. Returning empty result.")
        return []
    
    try:
        client = WorkspaceClient()
    except Exception as e:
        logger.error(f"Failed to initialize Databricks client: {e}")
        return []

    # use warehouse to execute query
    # Choose a running warehouse quickly; set a short wait_timeout to avoid UI stalls
    try:
        warehouse = next((x for x in client.warehouses.list() if x.state == State.RUNNING), None)
        if warehouse is None:
            # As a fallback pick the first one
            warehouse = next(iter(client.warehouses.list()))
        if warehouse.id is None:
            raise RuntimeError("Warehouse ID is None")
        logger.info(f"Executing query {query.replace('\n', '\t')} on warehouse: {warehouse.id}")
        execution = client.statement_execution.execute_statement(
            warehouse_id=warehouse.id, statement=query, wait_timeout="15s"
        )
    except Exception as e:
        logger.error(f"Failed to execute Databricks query: {e}")
        return []

    if execution.status is None:
        raise RuntimeError("Execution status is None")

    if execution.status.state != StatementState.SUCCEEDED:
        error_msg = f"Query failed with state: {execution.status.state}"
        if execution.status.error is not None:
            error_msg += f" - {execution.status.error.message}"
        raise RuntimeError(error_msg)

    # convert result to dictionaries
    if (
        execution.result is not None
        and execution.result.data_array is not None
        and execution.manifest is not None
        and execution.manifest.schema is not None
        and execution.manifest.schema.columns is not None
    ):
        col_names = [col.name or "" for col in execution.manifest.schema.columns]
        rows = execution.result.data_array
        return [dict(zip(col_names, row)) for row in rows]

    return []


class DatabricksModel(BaseModel):
    __catalog__: ClassVar[str]
    __schema__: ClassVar[str]
    __table__: ClassVar[str]

    @classmethod
    def table_name(cls) -> str:
        return f"{cls.__catalog__}.{cls.__schema__}.{cls.__table__}"

    @classmethod
    def fetch(cls: type[T], **params) -> Sequence[T]:
        raise NotImplementedError(f"Must implement fetch() method, but {cls.__name__} does not have it.")
