use crate::toolbox::{ClientTool, ClientToolAdapter, ToolDyn, basic::FinishDelegationTool};
use dabgent_integrations::databricks::DatabricksRestClient;
use eyre::Result;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;

// Args structs matching the Python implementation

fn default_limit() -> usize {
    1000
}

// Helper functions for pagination and filtering
fn apply_pagination<T>(items: Vec<T>, limit: usize, offset: usize) -> (Vec<T>, String) {
    let total = items.len();
    let paginated: Vec<T> = items.into_iter().skip(offset).take(limit).collect();
    let shown = paginated.len();

    let pagination_info = if total > limit + offset {
        format!("Showing {} items (offset {}, limit {}). Total: {}", shown, offset, limit, total)
    } else if offset > 0 {
        format!("Showing {} items (offset {}). Total: {}", shown, offset, total)
    } else if total > limit {
        format!("Showing {} items (limit {}). Total: {}", shown, limit, total)
    } else {
        format!("Showing all {} items", total)
    };

    (paginated, pagination_info)
}


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
    #[serde(default = "default_timeout")]
    pub timeout: u32,
}

fn default_timeout() -> u32 {
    45
}

// Tool implementations

pub struct DatabricksListCatalogs {
    client: Arc<DatabricksRestClient>,
}

impl DatabricksListCatalogs {
    pub fn new(client: Arc<DatabricksRestClient>) -> Self {
        Self { client }
    }
}

impl ClientTool<DatabricksRestClient> for DatabricksListCatalogs {
    type Args = DatabricksListCatalogsArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "databricks_list_catalogs".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "List all available catalogs in Unity Catalog".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {},
                "required": [],
            }),
        }
    }

    fn client(&self) -> &DatabricksRestClient {
        &self.client
    }

    async fn call(&self, _args: Self::Args) -> Result<Result<Self::Output, Self::Error>> {
        match self.client.list_catalogs().await {
            Ok(catalogs) => {
                if catalogs.is_empty() {
                    Ok(Ok("No catalogs found.".to_string()))
                } else {
                    let mut result_lines = vec![
                        format!("Found {} catalogs:", catalogs.len()),
                        "".to_string(),
                    ];

                    for catalog in &catalogs {
                        result_lines.push(format!("• {}", catalog));
                    }

                    Ok(Ok(result_lines.join("\n")))
                }
            }
            Err(e) => Ok(Err(format!("Failed to list catalogs: {}", e))),
        }
    }
}

pub struct DatabricksListSchemas {
    client: Arc<DatabricksRestClient>,
}

impl DatabricksListSchemas {
    pub fn new(client: Arc<DatabricksRestClient>) -> Self {
        Self { client }
    }
}

impl ClientTool<DatabricksRestClient> for DatabricksListSchemas {
    type Args = DatabricksListSchemasArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "databricks_list_schemas".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "List all schemas in a specific catalog with optional filtering and pagination".to_string(),
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

    fn client(&self) -> &DatabricksRestClient {
        &self.client
    }

    async fn call(&self, args: Self::Args) -> Result<Result<Self::Output, Self::Error>> {
        tracing::debug!("DatabricksListSchemas::call starting with catalog: {}", args.catalog_name);
        match self.client.list_schemas(&args.catalog_name, args.filter.as_deref()).await {
            Ok(schemas) => {
                tracing::debug!("DatabricksListSchemas::call succeeded, found {} schemas", schemas.len());

                if schemas.is_empty() {
                    let message = if args.filter.is_some() {
                        format!("No schemas found in catalog '{}' matching filter.", args.catalog_name)
                    } else {
                        format!("No schemas found in catalog '{}'.", args.catalog_name)
                    };
                    Ok(Ok(message))
                } else {
                    // Apply pagination
                    let (paginated_schemas, pagination_info) = apply_pagination(schemas, args.limit, args.offset);

                    let mut result_lines = vec![pagination_info, "".to_string()];

                    for schema in &paginated_schemas {
                        // Remove redundant catalog name from output
                        result_lines.push(format!("• {}", schema));
                    }

                    Ok(Ok(result_lines.join("\n")))
                }
            }
            Err(e) => {
                tracing::debug!("DatabricksListSchemas::call failed with error: {}", e);
                Ok(Err(format!("Failed to list schemas in catalog '{}': {}", args.catalog_name, e)))
            }
        }
    }
}

pub struct DatabricksListTables {
    client: Arc<DatabricksRestClient>,
}

impl DatabricksListTables {
    pub fn new(client: Arc<DatabricksRestClient>) -> Self {
        Self { client }
    }
}

impl ClientTool<DatabricksRestClient> for DatabricksListTables {
    type Args = DatabricksListTablesArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "databricks_list_tables".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
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
                        "description": "Skip tables user cannot access",
                        "default": true,
                    },
                },
                "required": ["catalog_name", "schema_name"],
            }),
        }
    }

    fn client(&self) -> &DatabricksRestClient {
        &self.client
    }

    async fn call(&self, args: Self::Args) -> Result<Result<Self::Output, Self::Error>> {
        match self.client.list_tables_for_catalog_schema(&args.catalog_name, &args.schema_name, args.exclude_inaccessible).await {
            Ok(tables) => {
                if tables.is_empty() {
                    Ok(Ok(format!("No tables found in '{}.{}'.", args.catalog_name, args.schema_name)))
                } else {
                    let mut result_lines = vec![
                        format!("Found {} tables in '{}.{}':", tables.len(), args.catalog_name, args.schema_name),
                        "".to_string(),
                    ];

                    for table in &tables {
                        let mut table_info = format!("• {} ({})", table.full_name, table.table_type);
                        if let Some(owner) = &table.owner {
                            table_info.push_str(&format!(" - Owner: {}", owner));
                        }
                        if let Some(comment) = &table.comment {
                            table_info.push_str(&format!(" - {}", comment));
                        }
                        result_lines.push(table_info);
                    }

                    Ok(Ok(result_lines.join("\n")))
                }
            }
            Err(e) => Ok(Err(format!("Failed to list tables in '{}.{}': {}", args.catalog_name, args.schema_name, e))),
        }
    }
}

pub struct DatabricksDescribeTable {
    client: Arc<DatabricksRestClient>,
}

impl DatabricksDescribeTable {
    pub fn new(client: Arc<DatabricksRestClient>) -> Self {
        Self { client }
    }
}

impl ClientTool<DatabricksRestClient> for DatabricksDescribeTable {
    type Args = DatabricksDescribeTableArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "databricks_describe_table".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
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
                        "description": "Number of sample rows to retrieve",
                        "default": 10,
                    },
                },
                "required": ["table_full_name"],
            }),
        }
    }

    fn client(&self) -> &DatabricksRestClient {
        &self.client
    }

    async fn call(&self, args: Self::Args) -> Result<Result<Self::Output, Self::Error>> {
        match self.client.get_table_details(&args.table_full_name, args.sample_size).await {
            Ok(details) => {
                // Format the table details similar to Python implementation
                let mut result_lines = vec![
                    format!("Table: {}", details.full_name),
                    format!("Table Type: {}", details.table_type),
                ];

                if let Some(owner) = &details.owner {
                    result_lines.push(format!("Owner: {}", owner));
                }

                if let Some(comment) = &details.comment {
                    result_lines.push(format!("Comment: {}", comment));
                }

                if let Some(row_count) = details.row_count {
                    result_lines.push(format!("Row Count: {}", row_count));
                }

                if let Some(storage_location) = &details.storage_location {
                    result_lines.push(format!("Storage Location: {}", storage_location));
                }

                if let Some(data_source_format) = &details.data_source_format {
                    result_lines.push(format!("Data Source Format: {}", data_source_format));
                }

                // Add column information
                if !details.columns.is_empty() {
                    result_lines.push(format!("\nColumns ({}):", details.columns.len()));
                    for col in &details.columns {
                        let mut col_info = format!("  - {}: {}", col.name, col.data_type);
                        if let Some(comment) = &col.comment {
                            col_info.push_str(&format!(" ({})", comment));
                        }
                        result_lines.push(col_info);
                    }
                }

                // Add sample data if available
                if let Some(sample_data) = &details.sample_data {
                    if !sample_data.is_empty() {
                        result_lines.push(format!("\nSample Data ({} rows):", sample_data.len()));
                        // Convert to a simple string representation
                        for (i, row) in sample_data.iter().enumerate() {
                            if i >= 5 { // Limit to first 5 rows for readability
                                result_lines.push("...".to_string());
                                break;
                            }
                            let row_str: Vec<String> = row.iter()
                                .map(|(k, v)| format!("{}: {}", k, format_value(v)))
                                .collect();
                            result_lines.push(format!("  Row {}: {}", i + 1, row_str.join(", ")));
                        }
                    }
                }

                Ok(Ok(result_lines.join("\n")))
            }
            Err(e) => Ok(Err(format!("Failed to describe table: {}", e))),
        }
    }
}

pub struct DatabricksExecuteQuery {
    client: Arc<DatabricksRestClient>,
}

impl DatabricksExecuteQuery {
    pub fn new(client: Arc<DatabricksRestClient>) -> Self {
        Self { client }
    }
}

impl ClientTool<DatabricksRestClient> for DatabricksExecuteQuery {
    type Args = DatabricksExecuteQueryArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "databricks_execute_query".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "Execute a SELECT query on Databricks and get results. Only SELECT queries are allowed for safety.".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL SELECT query to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Query timeout (must be between 5 and 50 or 0 for no timeout)",
                        "default": 45,
                    },
                },
                "required": ["query"],
            }),
        }
    }

    fn client(&self) -> &DatabricksRestClient {
        &self.client
    }

    async fn call(&self, args: Self::Args) -> Result<Result<Self::Output, Self::Error>> {
        // Basic validation - ensure it's a SELECT query
        let query_upper = args.query.trim().to_uppercase();
        if !query_upper.starts_with("SELECT") && !query_upper.starts_with("WITH") {
            return Ok(Err("Only SELECT queries are allowed".to_string()));
        }

        match self.client.execute_sql(&args.query).await {
            Ok(results) => {
                if results.is_empty() {
                    Ok(Ok("Query executed successfully but returned no results.".to_string()))
                } else {
                    let mut result_lines = vec![
                        format!("Query returned {} rows:", results.len()),
                        "".to_string(),
                    ];

                    // Show column names if available
                    if let Some(first_row) = results.first() {
                        let columns: Vec<String> = first_row.keys().cloned().collect();
                        result_lines.push(format!("Columns: {}", columns.join(", ")));
                        result_lines.push("".to_string());
                        result_lines.push("Results:".to_string());
                    }

                    // Show results (limit to first 100 rows for readability)
                    let display_limit = std::cmp::min(results.len(), 100);
                    for (i, row) in results.iter().take(display_limit).enumerate() {
                        let row_str: Vec<String> = row.iter()
                            .map(|(k, v)| format!("{}: {}", k, format_value(v)))
                            .collect();
                        result_lines.push(format!("  Row {}: {}", i + 1, row_str.join(", ")));
                    }

                    if results.len() > 100 {
                        result_lines.push(format!("\n... showing first 100 of {} total rows", results.len()));
                    }

                    Ok(Ok(result_lines.join("\n")))
                }
            }
            Err(e) => Ok(Err(format!("Failed to execute query: {}", e))),
        }
    }
}

// Helper function to format JSON values
fn format_value(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        Value::Bool(b) => b.to_string(),
        Value::Null => "null".to_string(),
        _ => format!("{:?}", value),
    }
}

// Public function to create a databricks toolset
pub fn databricks_toolset() -> Result<Vec<Box<dyn ToolDyn>>> {
    tracing::info!("Creating Databricks toolset...");
    let client = Arc::new(DatabricksRestClient::new().map_err(|e| {
        tracing::error!("Failed to create DatabricksRestClient: {}", e);
        eyre::eyre!("{}", e)
    })?);
    tracing::info!("DatabricksRestClient created successfully");

    Ok(vec![
        Box::new(ClientToolAdapter::new(DatabricksListCatalogs::new(client.clone()))),
        Box::new(ClientToolAdapter::new(DatabricksListSchemas::new(client.clone()))),
        Box::new(ClientToolAdapter::new(DatabricksListTables::new(client.clone()))),
        Box::new(ClientToolAdapter::new(DatabricksDescribeTable::new(client.clone()))),
        Box::new(ClientToolAdapter::new(DatabricksExecuteQuery::new(client.clone()))),
        Box::new(FinishDelegationTool),
    ])
}