use edda_integrations::{
    DatabricksDescribeTableArgs, DatabricksExecuteQueryArgs, DatabricksListCatalogsArgs,
    DatabricksListSchemasArgs, DatabricksListTablesArgs, DatabricksRestClient,
    DescribeTableRequest, ExecuteSqlRequest, ListSchemasRequest, ListTablesRequest,
    ToolResultDisplay,
};
use eyre::Result;
use rmcp::handler::server::router::tool::ToolRouter;
use rmcp::handler::server::wrapper::Parameters;
use rmcp::model::{CallToolResult, Content, ServerInfo};
use rmcp::{tool, tool_handler, tool_router, ErrorData, ServerHandler};
use std::sync::Arc;

#[derive(Clone)]
pub struct DatabricksRestProvider {
    client: Arc<DatabricksRestClient>,
    tool_router: ToolRouter<Self>,
}

#[tool_router]
impl DatabricksRestProvider {
    pub fn new() -> Result<Self> {
        let client = DatabricksRestClient::new()
            .map_err(|e| eyre::eyre!("Failed to create Databricks client: {}", e))?;
        Ok(Self {
            client: Arc::new(client),
            tool_router: Self::tool_router(),
        })
    }

    #[tool(
        name = "databricks_execute_sql",
        description = "Execute SQL query in Databricks. \
                       Only single SQL statements are supported - do not send multiple statements separated by semicolons. \
                       For multiple statements, call this tool separately for each one. \
                       DO NOT create catalogs, schemas or tables - requires metastore admin privileges. Query existing data instead. \
                       Timeout: 60 seconds for query execution."
    )]
    pub async fn execute_sql(
        &self,
        Parameters(args): Parameters<DatabricksExecuteQueryArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let request = ExecuteSqlRequest {
            query: args.query,
        };
        match self.client.execute_sql(&request).await {
            Ok(result) => Ok(CallToolResult::success(vec![Content::text(result.display())])),
            Err(e) => Err(ErrorData::internal_error(e.to_string(), None)),
        }
    }

    #[tool(name = "databricks_list_catalogs", description = "List all available Databricks catalogs")]
    pub async fn list_catalogs(
        &self,
        Parameters(_args): Parameters<DatabricksListCatalogsArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        match self.client.list_catalogs().await {
            Ok(result) => Ok(CallToolResult::success(vec![Content::text(result.display())])),
            Err(e) => Err(ErrorData::internal_error(e.to_string(), None)),
        }
    }

    #[tool(name = "databricks_list_schemas", description = "List all schemas in a Databricks catalog with pagination support")]
    pub async fn list_schemas(
        &self,
        Parameters(args): Parameters<DatabricksListSchemasArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let request = ListSchemasRequest {
            catalog_name: args.catalog_name,
            filter: args.filter,
            limit: args.limit,
            offset: args.offset,
        };
        match self.client.list_schemas(&request).await {
            Ok(result) => Ok(CallToolResult::success(vec![Content::text(result.display())])),
            Err(e) => Err(ErrorData::internal_error(e.to_string(), None)),
        }
    }

    #[tool(name = "databricks_find_tables", description = "Find or list tables in Databricks Unity Catalog. - To list all tables in a schema: provide catalog_name + schema_name - To search by name: use the 'filter' parameter (supports wildcards) - To search across all catalogs/schemas: omit catalog_name/schema_name Supports pagination (default limit: 500).")]
    pub async fn find_tables(
        &self,
        Parameters(args): Parameters<DatabricksListTablesArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let request = ListTablesRequest {
            catalog_name: args.catalog_name,
            schema_name: args.schema_name,
            filter: args.filter,
            limit: args.limit,
            offset: args.offset,
        };
        match self.client.list_tables(&request).await {
            Ok(result) => Ok(CallToolResult::success(vec![Content::text(result.display())])),
            Err(e) => Err(ErrorData::internal_error(e.to_string(), None)),
        }
    }

    #[tool(
        name = "databricks_describe_table",
        description = "Get detailed information about a Databricks table including schema and optional sample data"
    )]
    pub async fn describe_table(
        &self,
        Parameters(args): Parameters<DatabricksDescribeTableArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let request = DescribeTableRequest {
            table_full_name: args.table_full_name,
            sample_size: args.sample_size,
        };
        match self.client.describe_table(&request).await {
            Ok(result) => Ok(CallToolResult::success(vec![Content::text(result.display())])),
            Err(e) => Err(ErrorData::internal_error(e.to_string(), None)),
        }
    }
}

#[tool_handler]
impl ServerHandler for DatabricksRestProvider {
    fn get_info(&self) -> ServerInfo {
        crate::mcp_helpers::internal_server_info()
    }
}
