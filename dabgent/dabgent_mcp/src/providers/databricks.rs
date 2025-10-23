use dabgent_integrations::{
    DatabricksDescribeTableArgs, DatabricksExecuteQueryArgs, DatabricksListCatalogsArgs,
    DatabricksListSchemasArgs, DatabricksListTablesArgs, DatabricksRestClient,
    DescribeTableRequest, ExecuteSqlRequest, ListSchemasRequest, ListTablesRequest,
    ToolResultDisplay,
};
use eyre::Result;
use rmcp::handler::server::router::tool::ToolRouter;
use rmcp::handler::server::wrapper::Parameters;
use rmcp::model::{CallToolResult, Content, Implementation, ProtocolVersion, ServerCapabilities, ServerInfo};
use rmcp::{tool, tool_handler, tool_router, ErrorData, ServerHandler};
use std::sync::Arc;

#[derive(Clone)]
pub struct DatabricksProvider {
    client: Arc<DatabricksRestClient>,
    tool_router: ToolRouter<Self>,
}

#[tool_router]
impl DatabricksProvider {
    pub fn new() -> Result<Self> {
        let client = DatabricksRestClient::new()
            .map_err(|e| eyre::eyre!("Failed to create Databricks client: {}", e))?;
        Ok(Self {
            client: Arc::new(client),
            tool_router: Self::tool_router(),
        })
    }

    #[tool(name = "databricks_execute_sql", description = "Execute SQL query in Databricks")]
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

    #[tool(name = "databricks_list_tables", description = "List tables in a Databricks catalog and schema")]
    pub async fn list_tables(
        &self,
        Parameters(args): Parameters<DatabricksListTablesArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let request = ListTablesRequest {
            catalog_name: args.catalog_name,
            schema_name: args.schema_name,
            exclude_inaccessible: args.exclude_inaccessible,
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
impl ServerHandler for DatabricksProvider {
    fn get_info(&self) -> ServerInfo {
        ServerInfo {
            protocol_version: ProtocolVersion::V_2024_11_05,
            capabilities: ServerCapabilities::builder().enable_tools().build(),
            server_info: Implementation {
                name: "dabgent-mcp-databricks".to_string(),
                version: env!("CARGO_PKG_VERSION").to_string(),
                title: Some("Dabgent MCP - Databricks".to_string()),
                website_url: None,
                icons: None,
            },
            instructions: Some(
                "MCP server providing Databricks integration tools for querying data, exploring catalogs, schemas, and tables.".to_string(),
            ),
        }
    }
}
