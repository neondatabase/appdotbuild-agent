use super::agent::{Agent, AgentState, Command, Event};
use crate::toolbox::ToolCallExt;
use dabgent_integrations::databricks::DatabricksRestClient;
use dabgent_mq::{Envelope, EventHandler, EventStore, Handler};
use eyre::Result;
use rig::message::{ToolCall, ToolResult};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

// ============================================================================
// Argument Structs
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DatabricksListCatalogsArgs {
    // No parameters needed - lists all available catalogs
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DatabricksListSchemasArgs {
    pub catalog_name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub filter: Option<String>,
    #[serde(default = "default_limit")]
    pub limit: usize,
    #[serde(default)]
    pub offset: usize,
}

fn default_limit() -> usize {
    1000
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DatabricksListTablesArgs {
    pub catalog_name: String,
    pub schema_name: String,
    #[serde(default = "default_exclude_inaccessible")]
    pub exclude_inaccessible: bool,
}

fn default_exclude_inaccessible() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DatabricksDescribeTableArgs {
    pub table_full_name: String,
    #[serde(default = "default_sample_size")]
    pub sample_size: usize,
}

fn default_sample_size() -> usize {
    10
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DatabricksExecuteQueryArgs {
    pub query: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FinishDelegationArgs {
    pub summary: String,
}

// ============================================================================
// Helper Functions
// ============================================================================

fn apply_pagination<T>(items: Vec<T>, limit: usize, offset: usize) -> (Vec<T>, String) {
    let total = items.len();
    let paginated: Vec<T> = items.into_iter().skip(offset).take(limit).collect();
    let shown = paginated.len();

    let pagination_info = if total > limit + offset {
        format!(
            "Showing {} items (offset {}, limit {}). Total: {}",
            shown, offset, limit, total
        )
    } else if offset > 0 {
        format!(
            "Showing {} items (offset {}). Total: {}",
            shown, offset, total
        )
    } else if total > limit {
        format!(
            "Showing {} items (limit {}). Total: {}",
            shown, limit, total
        )
    } else {
        format!("Showing all {} items", total)
    };

    (paginated, pagination_info)
}

fn format_value(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        Value::Bool(b) => b.to_string(),
        Value::Null => "null".to_string(),
        _ => format!("{:?}", value),
    }
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
    ) -> Pin<Box<dyn Future<Output = DatabricksToolDynResult> + Send + 'a>>;
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
    ) -> Pin<Box<dyn Future<Output = DatabricksToolDynResult> + Send + 'a>> {
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
            Ok(catalogs) => {
                if catalogs.is_empty() {
                    Ok(Ok("No catalogs found.".to_string()))
                } else {
                    let mut lines =
                        vec![format!("Found {} catalogs:", catalogs.len()), String::new()];
                    for catalog in &catalogs {
                        lines.push(format!("• {}", catalog));
                    }
                    Ok(Ok(lines.join("\n")))
                }
            }
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
        match client.list_schemas(&args.catalog_name).await {
            Ok(mut schemas) => {
                // Apply filter if provided
                if let Some(filter) = &args.filter {
                    let filter_lower = filter.to_lowercase();
                    schemas.retain(|s| s.to_lowercase().contains(&filter_lower));
                }

                if schemas.is_empty() {
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
                    let (paginated_schemas, pagination_info) =
                        apply_pagination(schemas, args.limit, args.offset);

                    let mut lines = vec![pagination_info, String::new()];
                    for schema in &paginated_schemas {
                        lines.push(format!("• {}", schema));
                    }
                    Ok(Ok(lines.join("\n")))
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
        match client
            .list_tables_for_catalog_schema(
                &args.catalog_name,
                &args.schema_name,
                args.exclude_inaccessible,
            )
            .await
        {
            Ok(tables) => {
                if tables.is_empty() {
                    Ok(Ok(format!(
                        "No tables found in '{}.{}'.",
                        args.catalog_name, args.schema_name
                    )))
                } else {
                    let mut lines = vec![
                        format!(
                            "Found {} tables in '{}.{}':",
                            tables.len(),
                            args.catalog_name,
                            args.schema_name
                        ),
                        String::new(),
                    ];

                    for table in &tables {
                        let mut info = format!("• {} ({})", table.full_name, table.table_type);
                        if let Some(owner) = &table.owner {
                            info.push_str(&format!(" - Owner: {}", owner));
                        }
                        if let Some(comment) = &table.comment {
                            info.push_str(&format!(" - {}", comment));
                        }
                        lines.push(info);
                    }
                    Ok(Ok(lines.join("\n")))
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
        match client
            .get_table_details(&args.table_full_name, args.sample_size)
            .await
        {
            Ok(details) => {
                let mut lines = vec![
                    format!("Table: {}", details.full_name),
                    format!("Table Type: {}", details.table_type),
                ];

                if let Some(owner) = &details.owner {
                    lines.push(format!("Owner: {}", owner));
                }
                if let Some(comment) = &details.comment {
                    lines.push(format!("Comment: {}", comment));
                }
                if let Some(row_count) = details.row_count {
                    lines.push(format!("Row Count: {}", row_count));
                }
                if let Some(storage) = &details.storage_location {
                    lines.push(format!("Storage Location: {}", storage));
                }
                if let Some(format) = &details.data_source_format {
                    lines.push(format!("Data Source Format: {}", format));
                }

                if !details.columns.is_empty() {
                    lines.push(format!("\nColumns ({}):", details.columns.len()));
                    for col in &details.columns {
                        let mut col_info = format!("  - {}: {}", col.name, col.data_type);
                        if let Some(comment) = &col.comment {
                            col_info.push_str(&format!(" ({})", comment));
                        }
                        lines.push(col_info);
                    }
                }

                if let Some(sample) = &details.sample_data {
                    if !sample.is_empty() {
                        lines.push(format!("\nSample Data ({} rows):", sample.len()));
                        for (i, row) in sample.iter().enumerate().take(5) {
                            let row_str: Vec<String> = row
                                .iter()
                                .map(|(k, v)| format!("{}: {}", k, format_value(v)))
                                .collect();
                            lines.push(format!("  Row {}: {}", i + 1, row_str.join(", ")));
                        }
                        if sample.len() > 5 {
                            lines.push("...".to_string());
                        }
                    }
                }

                Ok(Ok(lines.join("\n")))
            }
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

        match client.execute_sql(&args.query).await {
            Ok(results) => {
                if results.is_empty() {
                    Ok(Ok(
                        "Query executed successfully but returned no results.".to_string()
                    ))
                } else {
                    let mut lines = vec![
                        format!("Query returned {} rows:", results.len()),
                        String::new(),
                    ];

                    if let Some(first) = results.first() {
                        let columns: Vec<String> = first.keys().cloned().collect();
                        lines.push(format!("Columns: {}", columns.join(", ")));
                        lines.push(String::new());
                        lines.push("Results:".to_string());
                    }

                    let limit = std::cmp::min(results.len(), 100);
                    for (i, row) in results.iter().take(limit).enumerate() {
                        let row_str: Vec<String> = row
                            .iter()
                            .map(|(k, v)| format!("{}: {}", k, format_value(v)))
                            .collect();
                        lines.push(format!("  Row {}: {}", i + 1, row_str.join(", ")));
                    }

                    if results.len() > 100 {
                        lines.push(format!(
                            "\n... showing first 100 of {} total rows",
                            results.len()
                        ));
                    }

                    Ok(Ok(lines.join("\n")))
                }
            }
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
    ) -> Option<(&'a ToolCall, &'a Box<dyn DatabricksToolDyn>)> {
        self.get_tool(&call.function.name).map(|tool| (call, tool))
    }

    fn get_tool(&self, name: &str) -> Option<&Box<dyn DatabricksToolDyn>> {
        self.tools.iter().find(|t| t.name() == name)
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
