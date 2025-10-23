use super::agent::{Agent, AgentState, Command, Event};
use crate::toolbox::ToolCallExt;
use dabgent_integrations::{
    DatabricksDescribeTableArgs, DatabricksExecuteQueryArgs, DatabricksListCatalogsArgs,
    DatabricksListSchemasArgs, DatabricksListTablesArgs, DatabricksRestClient,
    DescribeTableRequest, ExecuteSqlRequest, ListSchemasRequest, ListTablesRequest,
    ToolResultDisplay,
};
use dabgent_mq::{Envelope, EventHandler, EventStore, Handler};
use dabgent_sandbox::FutureBoxed;
use eyre::Result;
use rig::message::{ToolCall, ToolResult};
use serde::{Deserialize, Serialize};
use std::future::Future;
use std::sync::Arc;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FinishDelegationArgs {
    pub summary: String,
}

pub trait DatabricksTool: Send + Sync {
    type Args: for<'a> Deserialize<'a> + Serialize + Send + Sync;
    type Output: Serialize + Send + Sync;
    type Error: Serialize + Send + Sync;
    fn name(&self) -> String;
    fn definition(&self) -> rig::completion::ToolDefinition;
    fn call(
        &self,
        args: Self::Args,
        client: &DatabricksRestClient,
    ) -> impl Future<Output = Result<Result<Self::Output, Self::Error>>> + Send;
}

type DatabricksToolDynResult = Result<Result<serde_json::Value, serde_json::Value>>;

pub trait DatabricksToolDyn: Send + Sync {
    fn name(&self) -> String;
    fn definition(&self) -> rig::completion::ToolDefinition;
    fn call<'a>(
        &'a self,
        args: serde_json::Value,
        client: &'a DatabricksRestClient,
    ) -> FutureBoxed<'a, DatabricksToolDynResult>;
}

impl<T: DatabricksTool> DatabricksToolDyn for T {
    fn name(&self) -> String {
        DatabricksTool::name(self)
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        self.definition()
    }

    fn call<'a>(
        &'a self,
        args: serde_json::Value,
        client: &'a DatabricksRestClient,
    ) -> FutureBoxed<'a, DatabricksToolDynResult> {
        Box::pin(async move {
            match serde_json::from_value::<<Self as DatabricksTool>::Args>(args) {
                Ok(args) => {
                    let result = DatabricksTool::call(self, args, client).await?;
                    let result = match result {
                        Ok(output) => Ok(serde_json::to_value(output)?),
                        Err(error) => Err(serde_json::to_value(error)?),
                    };
                    Ok(result)
                }
                Err(error) => Ok(Err(serde_json::to_value(error.to_string())?)),
            }
        })
    }
}

// ============================================================================
// Tool Implementations
// ============================================================================

pub struct DatabricksListCatalogs;

impl DatabricksTool for DatabricksListCatalogs {
    type Args = DatabricksListCatalogsArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "databricks_list_catalogs".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: DatabricksTool::name(self),
            description: "List all available catalogs in Unity Catalog".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {},
                "required": [],
            }),
        }
    }

    async fn call(
        &self,
        _args: Self::Args,
        client: &DatabricksRestClient,
    ) -> Result<Result<Self::Output, Self::Error>> {
        match client.list_catalogs().await {
            Ok(result) => Ok(Ok(result.display())),
            Err(e) => Ok(Err(format!("Failed to list catalogs: {}", e))),
        }
    }
}

pub struct DatabricksListSchemas;

impl DatabricksTool for DatabricksListSchemas {
    type Args = DatabricksListSchemasArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "databricks_list_schemas".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: DatabricksTool::name(self),
            description:
                "List all schemas in a specific catalog with optional filtering and pagination"
                    .to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "catalog_name": {
                        "type": "string",
                        "description": "Name of the catalog to list schemas from",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Optional filter to search for schemas by name (case-insensitive substring match)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of schemas to return (default: 1000)",
                        "default": 1000,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Number of schemas to skip (default: 0)",
                        "default": 0,
                    },
                },
                "required": ["catalog_name"],
            }),
        }
    }

    async fn call(
        &self,
        args: Self::Args,
        client: &DatabricksRestClient,
    ) -> Result<Result<Self::Output, Self::Error>> {
        let request = ListSchemasRequest {
            catalog_name: args.catalog_name.clone(),
            filter: args.filter.clone(),
            limit: args.limit,
            offset: args.offset,
        };
        match client.list_schemas(&request).await {
            Ok(result) => {
                if result.schemas.is_empty() {
                    let message = if args.filter.is_some() {
                        format!(
                            "No schemas found in catalog '{}' matching filter.",
                            args.catalog_name
                        )
                    } else {
                        format!("No schemas found in catalog '{}'.", args.catalog_name)
                    };
                    Ok(Ok(message))
                } else {
                    Ok(Ok(result.display()))
                }
            }
            Err(e) => Ok(Err(format!(
                "Failed to list schemas in catalog '{}': {}",
                args.catalog_name, e
            ))),
        }
    }
}

pub struct DatabricksListTables;

impl DatabricksTool for DatabricksListTables {
    type Args = DatabricksListTablesArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "databricks_list_tables".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: DatabricksTool::name(self),
            description: "List tables in a specific catalog and schema".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "catalog_name": {
                        "type": "string",
                        "description": "Catalog name (required)",
                    },
                    "schema_name": {
                        "type": "string",
                        "description": "Schema name (required)",
                    },
                    "exclude_inaccessible": {
                        "type": "boolean",
                        "description": "Skip tables user cannot access (default: true)",
                        "default": true,
                    },
                },
                "required": ["catalog_name", "schema_name"],
            }),
        }
    }

    async fn call(
        &self,
        args: Self::Args,
        client: &DatabricksRestClient,
    ) -> Result<Result<Self::Output, Self::Error>> {
        let request = ListTablesRequest {
            catalog_name: args.catalog_name.clone(),
            schema_name: args.schema_name.clone(),
            exclude_inaccessible: args.exclude_inaccessible,
        };
        match client.list_tables(&request).await {
            Ok(result) => {
                if result.tables.is_empty() {
                    Ok(Ok(format!(
                        "No tables found in '{}.{}'.",
                        args.catalog_name, args.schema_name
                    )))
                } else {
                    Ok(Ok(result.display()))
                }
            }
            Err(e) => Ok(Err(format!(
                "Failed to list tables in '{}.{}': {}",
                args.catalog_name, args.schema_name, e
            ))),
        }
    }
}

pub struct DatabricksDescribeTable;

impl DatabricksTool for DatabricksDescribeTable {
    type Args = DatabricksDescribeTableArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "databricks_describe_table".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: DatabricksTool::name(self),
            description: "Get comprehensive table details including metadata, columns, sample data, and row count".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "table_full_name": {
                        "type": "string",
                        "description": "Full table name in format 'catalog.schema.table'",
                    },
                    "sample_size": {
                        "type": "integer",
                        "description": "Number of sample rows to retrieve (default: 10)",
                        "default": 10,
                    },
                },
                "required": ["table_full_name"],
            }),
        }
    }

    async fn call(
        &self,
        args: Self::Args,
        client: &DatabricksRestClient,
    ) -> Result<Result<Self::Output, Self::Error>> {
        let request = DescribeTableRequest {
            table_full_name: args.table_full_name.clone(),
            sample_size: args.sample_size,
        };
        match client.describe_table(&request).await {
            Ok(details) => Ok(Ok(details.display())),
            Err(e) => Ok(Err(format!("Failed to describe table: {}", e))),
        }
    }
}

pub struct DatabricksExecuteQuery;

impl DatabricksTool for DatabricksExecuteQuery {
    type Args = DatabricksExecuteQueryArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "databricks_execute_query".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: DatabricksTool::name(self),
            description: "Execute a SELECT query on Databricks and get results. Only SELECT queries are allowed for safety.".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL SELECT query to execute",
                    },
                },
                "required": ["query"],
            }),
        }
    }

    async fn call(
        &self,
        args: Self::Args,
        client: &DatabricksRestClient,
    ) -> Result<Result<Self::Output, Self::Error>> {
        let query_upper = args.query.trim().to_uppercase();
        if !query_upper.starts_with("SELECT") && !query_upper.starts_with("WITH") {
            return Ok(Err("Only SELECT queries are allowed".to_string()));
        }

        let request = ExecuteSqlRequest {
            query: args.query.clone(),
        };
        match client.execute_sql(&request).await {
            Ok(result) => Ok(Ok(result.display())),
            Err(e) => Ok(Err(format!("Failed to execute query: {}", e))),
        }
    }
}

pub struct FinishDelegation;

impl DatabricksTool for FinishDelegation {
    type Args = FinishDelegationArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "finish_delegation".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: DatabricksTool::name(self),
            description: "Mark the task as complete and provide a summary of what was accomplished"
                .to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Summary of the completed work",
                    },
                },
                "required": ["summary"],
            }),
        }
    }

    async fn call(
        &self,
        _args: Self::Args,
        _client: &DatabricksRestClient,
    ) -> Result<Result<Self::Output, Self::Error>> {
        Ok(Ok(_args.summary))
    }
}

// ============================================================================
// Databricks Tool Handler
// ============================================================================

pub struct DatabricksToolHandler {
    tools: Vec<Box<dyn DatabricksToolDyn>>,
    client: Arc<DatabricksRestClient>,
}

impl DatabricksToolHandler {
    pub fn new(client: Arc<DatabricksRestClient>, tools: Vec<Box<dyn DatabricksToolDyn>>) -> Self {
        Self { tools, client }
    }

    async fn run_tools(&self, calls: &[ToolCall]) -> Result<Vec<ToolResult>> {
        let mut results = Vec::new();
        for (call, tool) in calls.iter().filter_map(|call| self.match_tool(call)) {
            let result = tool
                .call(call.function.arguments.clone(), &self.client)
                .await?;
            results.push(call.to_result(result));
        }
        Ok(results)
    }

    fn match_tool<'a>(
        &'a self,
        call: &'a ToolCall,
    ) -> Option<(&'a ToolCall, &'a dyn DatabricksToolDyn)> {
        self.get_tool(&call.function.name).map(|tool| (call, tool))
    }

    fn get_tool(&self, name: &str) -> Option<&dyn DatabricksToolDyn> {
        self.tools
            .iter()
            .find(|t| t.name() == name)
            .map(AsRef::as_ref)
    }

    pub fn definitions(&self) -> Vec<rig::completion::ToolDefinition> {
        self.tools.iter().map(|t| t.definition()).collect()
    }
}

impl<A: Agent, ES: EventStore> EventHandler<AgentState<A>, ES> for DatabricksToolHandler {
    async fn process(
        &mut self,
        handler: &Handler<AgentState<A>, ES>,
        event: &Envelope<AgentState<A>>,
    ) -> Result<()> {
        if let Event::ToolCalls { calls } = &event.data {
            let results = self.run_tools(calls).await?;
            if !results.is_empty() {
                handler
                    .execute_with_metadata(
                        &event.aggregate_id,
                        Command::PutToolResults { results },
                        event.metadata.clone(),
                    )
                    .await?;
            }
        }
        Ok(())
    }
}

pub fn toolbox() -> Vec<Box<dyn DatabricksToolDyn>> {
    let tools: Vec<Box<dyn DatabricksToolDyn>> = vec![
        Box::new(DatabricksListCatalogs),
        Box::new(DatabricksListSchemas),
        Box::new(DatabricksListTables),
        Box::new(DatabricksDescribeTable),
        Box::new(DatabricksExecuteQuery),
        Box::new(FinishDelegation),
    ];
    tools
}
