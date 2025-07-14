import pytest
import polars as pl

from integrations.dbrx import DatabricksClient, TableMetadata, TableDetails, ColumnMetadata
from tests.test_utils import requires_databricks, requires_databricks_reason

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.fixture(scope="module")
def databricks_client():
    """Create a real Databricks client for testing.
    
    Uses module scope to reuse the same client instance across all tests,
    which allows the LRU cache to be effective.
    """
    return DatabricksClient()


@pytest.mark.skipif(requires_databricks(), reason=requires_databricks_reason)
async def test_databricks_client_initialization(databricks_client):
    """Test that DatabricksClient can be initialized with real credentials."""
    assert databricks_client.client is not None


@pytest.mark.skipif(requires_databricks(), reason=requires_databricks_reason)
async def test_list_tables_all(databricks_client):
    """Test listing all tables in the workspace."""
    tables = databricks_client.list_tables()

    assert isinstance(tables, list)
    # should have at least some tables in a real workspace
    assert len(tables) > 0

    # check structure of returned tables
    for table in tables[:5]:  # check first 5 tables
        assert isinstance(table, TableMetadata)
        assert table.catalog is not None
        assert table.schema is not None
        assert table.name is not None
        assert table.full_name is not None
        assert table.table_type is not None
        assert "." in table.full_name  # should be catalog.schema.table format


@pytest.mark.skipif(requires_databricks(), reason=requires_databricks_reason)
async def test_list_tables_with_catalog_filter(databricks_client):
    """Test listing tables with catalog filtering."""
    # first get all tables to find a catalog that exists
    all_tables = databricks_client.list_tables()
    if not all_tables:
        pytest.skip("No tables found in workspace")

    # get the first catalog
    test_catalog = all_tables[0].catalog

    # now filter by that catalog
    filtered_tables = databricks_client.list_tables(catalog=test_catalog)

    assert isinstance(filtered_tables, list)
    assert len(filtered_tables) > 0

    # all returned tables should be from the specified catalog
    for table in filtered_tables:
        assert table.catalog == test_catalog


@pytest.mark.skipif(requires_databricks(), reason=requires_databricks_reason)
async def test_get_table_details(databricks_client):
    """Test getting details for a real table."""
    # first get a table to test with
    tables = databricks_client.list_tables()
    if not tables:
        pytest.skip("No tables found in workspace")

    # use the first table
    test_table = tables[0]

    # get details
    details = databricks_client.get_table_details(test_table.full_name)

    assert isinstance(details, TableDetails)
    assert details.metadata is not None
    assert details.columns is not None
    assert isinstance(details.columns, list)
    assert len(details.columns) > 0

    # check metadata
    assert details.metadata.full_name == test_table.full_name
    assert details.metadata.catalog == test_table.catalog
    assert details.metadata.schema == test_table.schema
    assert details.metadata.name == test_table.name

    # check columns
    for col in details.columns:
        assert isinstance(col, ColumnMetadata)
        assert col.name is not None
        assert col.data_type is not None
        assert isinstance(col.position, int)

    # check sample data if available
    if details.sample_data is not None:
        assert isinstance(details.sample_data, pl.DataFrame)
        assert len(details.sample_data.columns) == len(details.columns)

    # row count should be a non-negative integer
    assert details.row_count is not None
    assert isinstance(details.row_count, int)
    assert details.row_count >= 0


@pytest.mark.skipif(requires_databricks(), reason=requires_databricks_reason)
async def test_execute_query_valid_select(databricks_client):
    """Test executing a valid SELECT query."""
    # first get a table to query
    tables = databricks_client.list_tables()
    if not tables:
        pytest.skip("No tables found in workspace")

    test_table = tables[0]
    query = f"SELECT * FROM {test_table.full_name} LIMIT 5"

    result = databricks_client.execute_query(query)

    assert isinstance(result, pl.DataFrame)
    # result should have at most 5 rows due to LIMIT
    assert len(result) <= 5
    # should have at least one column
    assert len(result.columns) > 0


@pytest.mark.skipif(requires_databricks(), reason=requires_databricks_reason)
async def test_execute_query_validation_non_select(databricks_client):
    """Test that non-SELECT queries are rejected."""
    # test various non-SELECT statements
    invalid_queries = [
        "DROP TABLE test_table",
        "CREATE TABLE test AS SELECT 1",
        "INSERT INTO test VALUES (1)",
        "UPDATE test SET col = 1",
        "DELETE FROM test"
    ]

    for query in invalid_queries:
        with pytest.raises(ValueError, match="Only SELECT queries are allowed"):
            databricks_client.execute_query(query)


@pytest.mark.skipif(requires_databricks(), reason=requires_databricks_reason)
async def test_execute_query_invalid_table(databricks_client):
    """Test executing query on non-existent table."""
    invalid_query = "SELECT * FROM non_existent_catalog.non_existent_schema.non_existent_table"

    with pytest.raises(RuntimeError, match="Query failed"):
        databricks_client.execute_query(invalid_query)


@pytest.mark.skipif(requires_databricks(), reason=requires_databricks_reason)
async def test_has_table_access_existing_table(databricks_client):
    """Test access check for existing table."""
    # get a table we know exists
    tables = databricks_client.list_tables()
    if not tables:
        pytest.skip("No tables found in workspace")

    test_table = tables[0]

    # we should have access to a table that was returned by list_tables
    has_access = databricks_client._has_table_access(test_table.full_name)
    assert has_access is True


@pytest.mark.skipif(requires_databricks(), reason=requires_databricks_reason)
async def test_has_table_access_nonexistent_table(databricks_client):
    """Test access check for non-existent table."""
    # use a clearly non-existent table name
    nonexistent_table = "definitely_nonexistent_catalog.nonexistent_schema.nonexistent_table"

    has_access = databricks_client._has_table_access(nonexistent_table)
    assert has_access is False


@pytest.mark.skipif(requires_databricks(), reason=requires_databricks_reason)
async def test_get_table_details_invalid_table_name_format(databricks_client):
    """Test that invalid table name format raises ValueError."""
    invalid_names = [
        "just_table_name",
        "schema.table",
        "catalog.schema.table.extra",
        ""
    ]

    for invalid_name in invalid_names:
        with pytest.raises(ValueError, match="Invalid table name format"):
            databricks_client.get_table_details(invalid_name)


@pytest.mark.skipif(requires_databricks(), reason=requires_databricks_reason)
async def test_execute_query_empty_result(databricks_client):
    """Test executing query that returns no results."""
    # get a table to create a query that will return no results
    tables = databricks_client.list_tables()
    if not tables:
        pytest.skip("No tables found in workspace")

    test_table = tables[0]
    # create a query that should return no results
    query = f"SELECT * FROM {test_table.full_name} WHERE 1 = 0"

    result = databricks_client.execute_query(query)

    assert isinstance(result, pl.DataFrame)
    assert len(result) == 0
    # should still have column structure even with no rows
    assert len(result.columns) > 0


@pytest.mark.skipif(requires_databricks(), reason=requires_databricks_reason)
async def test_list_tables_exclude_inaccessible(databricks_client):
    """Test that exclude_inaccessible parameter works correctly."""
    # test with exclude_inaccessible=True (default)
    accessible_tables = databricks_client.list_tables(exclude_inaccessible=True)

    # test with exclude_inaccessible=False
    all_tables = databricks_client.list_tables(exclude_inaccessible=False)

    # accessible tables should be subset of all tables
    assert len(accessible_tables) <= len(all_tables)

    # all accessible tables should be in the all_tables list
    accessible_names = {table.full_name for table in accessible_tables}
    all_names = {table.full_name for table in all_tables}
    assert accessible_names.issubset(all_names)
