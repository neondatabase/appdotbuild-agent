use anyhow::{Result, anyhow};
use log::{debug, info};
use reqwest;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::time::Duration;
use tokio::time::sleep;

const SQL_WAREHOUSES_ENDPOINT: &str = "/api/2.0/sql/warehouses";
const SQL_STATEMENTS_ENDPOINT: &str = "/api/2.0/sql/statements";
const UNITY_CATALOG_TABLES_ENDPOINT: &str = "/api/2.1/unity-catalog/tables";
const UNITY_CATALOG_CATALOGS_ENDPOINT: &str = "/api/2.1/unity-catalog/catalogs";
const UNITY_CATALOG_SCHEMAS_ENDPOINT: &str = "/api/2.1/unity-catalog/schemas";
const DEFAULT_WAIT_TIMEOUT: &str = "30s";
const MAX_POLL_ATTEMPTS: usize = 30;

#[derive(Debug, Deserialize)]
struct TableResponse {
    table_type: Option<String>,
    owner: Option<String>,
    comment: Option<String>,
    storage_location: Option<String>,
    data_source_format: Option<String>,
    columns: Option<Vec<TableColumn>>,
}

#[derive(Debug, Deserialize)]
struct TableColumn {
    name: Option<String>,
    type_name: Option<String>,
    comment: Option<String>,
}

#[derive(Debug, Deserialize)]
struct TablesListResponse {
    tables: Option<Vec<TableSummary>>,
    next_page_token: Option<String>,
}

#[derive(Debug, Deserialize)]
struct TableSummary {
    name: String,
    catalog_name: String,
    schema_name: String,
    table_type: Option<String>,
    owner: Option<String>,
    comment: Option<String>,
}

#[derive(Debug, Deserialize)]
struct CatalogsListResponse {
    catalogs: Option<Vec<CatalogSummary>>,
    next_page_token: Option<String>,
}

#[derive(Debug, Deserialize)]
struct CatalogSummary {
    name: String,
}

#[derive(Debug, Deserialize)]
struct SchemasListResponse {
    schemas: Option<Vec<SchemaSummary>>,
    next_page_token: Option<String>,
}

#[derive(Debug, Deserialize)]
struct SchemaSummary {
    name: String,
}

// ============================================================================
// Helper Functions
// ============================================================================

fn apply_pagination<T>(items: Vec<T>, limit: usize, offset: usize) -> (Vec<T>, usize, usize) {
    let total = items.len();
    let paginated: Vec<T> = items.into_iter().skip(offset).take(limit).collect();
    let shown = paginated.len();
    (paginated, total, shown)
}

// ============================================================================
// Argument Types (shared between agent and MCP)
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, Default)]
#[serde(default)]
pub struct DatabricksListCatalogsArgs {
    // no parameters needed - lists all available catalogs
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
pub struct DatabricksListSchemasArgs {
    pub catalog_name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub filter: Option<String>,
    #[serde(default = "default_limit")]
    pub limit: usize,
    #[serde(default)]
    pub offset: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
pub struct DatabricksListTablesArgs {
    pub catalog_name: String,
    pub schema_name: String,
    #[serde(default = "default_exclude_inaccessible")]
    pub exclude_inaccessible: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
pub struct DatabricksDescribeTableArgs {
    pub table_full_name: String,
    #[serde(default = "default_sample_size")]
    pub sample_size: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
pub struct DatabricksExecuteQueryArgs {
    pub query: String,
}

// ============================================================================
// Request Types (internal to client)
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecuteSqlRequest {
    pub query: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ListSchemasRequest {
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
pub struct ListTablesRequest {
    pub catalog_name: String,
    pub schema_name: String,
    #[serde(default = "default_exclude_inaccessible")]
    pub exclude_inaccessible: bool,
}

fn default_exclude_inaccessible() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DescribeTableRequest {
    pub table_full_name: String,
    #[serde(default = "default_sample_size")]
    pub sample_size: usize,
}

fn default_sample_size() -> usize {
    5
}

// ============================================================================
// Response Types
// ============================================================================

#[derive(Debug, Serialize, Deserialize)]
pub struct TableDetails {
    pub full_name: String,
    pub table_type: String,
    pub owner: Option<String>,
    pub comment: Option<String>,
    pub storage_location: Option<String>,
    pub data_source_format: Option<String>,
    pub columns: Vec<ColumnMetadata>,
    pub sample_data: Option<Vec<HashMap<String, Value>>>,
    pub row_count: Option<i64>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ColumnMetadata {
    pub name: String,
    pub data_type: String,
    pub comment: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct TableInfo {
    pub name: String,
    pub catalog_name: String,
    pub schema_name: String,
    pub full_name: String,
    pub table_type: String,
    pub owner: Option<String>,
    pub comment: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ListCatalogsResult {
    pub catalogs: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ListSchemasResult {
    pub schemas: Vec<String>,
    pub total_count: usize,
    pub shown_count: usize,
    pub offset: usize,
    pub limit: usize,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ListTablesResult {
    pub tables: Vec<TableInfo>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ExecuteSqlResult {
    pub rows: Vec<HashMap<String, Value>>,
}

// ============================================================================
// Display Trait for Tool Results
// ============================================================================

use crate::ToolResultDisplay;

impl ToolResultDisplay for ListCatalogsResult {
    fn display(&self) -> String {
        if self.catalogs.is_empty() {
            "No catalogs found.".to_string()
        } else {
            let mut lines = vec![format!("Found {} catalogs:", self.catalogs.len()), String::new()];
            for catalog in &self.catalogs {
                lines.push(format!("• {}", catalog));
            }
            lines.join("\n")
        }
    }
}

impl ToolResultDisplay for ListSchemasResult {
    fn display(&self) -> String {
        let pagination_info = if self.total_count > self.limit + self.offset {
            format!(
                "Showing {} items (offset {}, limit {}). Total: {}",
                self.shown_count, self.offset, self.limit, self.total_count
            )
        } else if self.offset > 0 {
            format!(
                "Showing {} items (offset {}). Total: {}",
                self.shown_count, self.offset, self.total_count
            )
        } else if self.total_count > self.limit {
            format!(
                "Showing {} items (limit {}). Total: {}",
                self.shown_count, self.limit, self.total_count
            )
        } else {
            format!("Showing all {} items", self.total_count)
        };

        if self.schemas.is_empty() {
            pagination_info
        } else {
            let mut lines = vec![pagination_info, String::new()];
            for schema in &self.schemas {
                lines.push(format!("• {}", schema));
            }
            lines.join("\n")
        }
    }
}

impl ToolResultDisplay for ListTablesResult {
    fn display(&self) -> String {
        if self.tables.is_empty() {
            "No tables found.".to_string()
        } else {
            let mut lines = vec![format!("Found {} tables:", self.tables.len()), String::new()];

            for table in &self.tables {
                let mut info = format!("• {} ({})", table.full_name, table.table_type);
                if let Some(owner) = &table.owner {
                    info.push_str(&format!(" - Owner: {}", owner));
                }
                if let Some(comment) = &table.comment {
                    info.push_str(&format!(" - {}", comment));
                }
                lines.push(info);
            }
            lines.join("\n")
        }
    }
}

impl ToolResultDisplay for TableDetails {
    fn display(&self) -> String {
        let mut lines = vec![
            format!("Table: {}", self.full_name),
            format!("Table Type: {}", self.table_type),
        ];

        if let Some(owner) = &self.owner {
            lines.push(format!("Owner: {}", owner));
        }
        if let Some(comment) = &self.comment {
            lines.push(format!("Comment: {}", comment));
        }
        if let Some(row_count) = self.row_count {
            lines.push(format!("Row Count: {}", row_count));
        }
        if let Some(storage) = &self.storage_location {
            lines.push(format!("Storage Location: {}", storage));
        }
        if let Some(format) = &self.data_source_format {
            lines.push(format!("Data Source Format: {}", format));
        }

        if !self.columns.is_empty() {
            lines.push(format!("\nColumns ({}):", self.columns.len()));
            for col in &self.columns {
                let mut col_info = format!("  - {}: {}", col.name, col.data_type);
                if let Some(comment) = &col.comment {
                    col_info.push_str(&format!(" ({})", comment));
                }
                lines.push(col_info);
            }
        }

        if let Some(sample) = &self.sample_data {
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

        lines.join("\n")
    }
}

impl ToolResultDisplay for ExecuteSqlResult {
    fn display(&self) -> String {
        if self.rows.is_empty() {
            "Query executed successfully but returned no results.".to_string()
        } else {
            let mut lines = vec![
                format!("Query returned {} rows:", self.rows.len()),
                String::new(),
            ];

            if let Some(first) = self.rows.first() {
                let columns: Vec<String> = first.keys().cloned().collect();
                lines.push(format!("Columns: {}", columns.join(", ")));
                lines.push(String::new());
                lines.push("Results:".to_string());
            }

            let limit = std::cmp::min(self.rows.len(), 100);
            for (i, row) in self.rows.iter().take(limit).enumerate() {
                let row_str: Vec<String> = row
                    .iter()
                    .map(|(k, v)| format!("{}: {}", k, format_value(v)))
                    .collect();
                lines.push(format!("  Row {}: {}", i + 1, row_str.join(", ")));
            }

            if self.rows.len() > 100 {
                lines.push(format!(
                    "\n... showing first 100 of {} total rows",
                    self.rows.len()
                ));
            }

            lines.join("\n")
        }
    }
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

#[derive(Debug, Deserialize)]
struct WarehouseListResponse {
    warehouses: Vec<Warehouse>,
}

#[derive(Debug, Deserialize)]
struct Warehouse {
    id: String,
    name: Option<String>,
    state: String,
}

#[derive(Debug, Serialize)]
struct SqlStatementRequest {
    statement: String,
    warehouse_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    catalog: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    schema: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    parameters: Option<Vec<Value>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    row_limit: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    byte_limit: Option<i64>,
    disposition: String,
    format: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    wait_timeout: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    on_wait_timeout: Option<String>,
}

#[derive(Debug, Deserialize)]
struct SqlStatementResponse {
    statement_id: String,
    status: Option<StatementStatus>,
    manifest: Option<ResultManifest>,
    result: Option<StatementResult>,
}

#[derive(Debug, Deserialize)]
struct StatementStatus {
    state: String,
    error: Option<StatementError>,
}

#[derive(Debug, Deserialize)]
struct StatementError {
    message: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ResultManifest {
    schema: Option<Schema>,
}

#[derive(Debug, Deserialize)]
struct Schema {
    columns: Vec<Column>,
}

#[derive(Debug, Deserialize)]
struct Column {
    name: String,
}

#[derive(Debug, Deserialize)]
struct StatementResult {
    data_array: Option<Vec<Vec<Option<String>>>>,
}

pub struct DatabricksRestClient {
    host: String,
    token: String,
    client: reqwest::Client,
}

impl DatabricksRestClient {
    pub fn new() -> Result<Self> {
        let host = std::env::var("DATABRICKS_HOST")
            .map_err(|_| anyhow!("DATABRICKS_HOST environment variable not set"))?;
        let token = std::env::var("DATABRICKS_TOKEN")
            .map_err(|_| anyhow!("DATABRICKS_TOKEN environment variable not set"))?;

        let host = if host.starts_with("http") {
            host
        } else {
            format!("https://{}", host)
        };

        Ok(Self {
            host,
            token,
            client: reqwest::Client::new(),
        })
    }

    fn auth_headers(&self) -> reqwest::header::HeaderMap {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(
            "Authorization",
            format!("Bearer {}", self.token).parse().unwrap(),
        );
        headers.insert("Content-Type", "application/json".parse().unwrap());
        headers
    }

    async fn api_request<T>(
        &self,
        method: reqwest::Method,
        url: &str,
        body: Option<&impl Serialize>,
    ) -> Result<T>
    where
        T: for<'de> Deserialize<'de>,
    {
        debug!("Making {} request to {}", method, url);

        let mut request = self
            .client
            .request(method, url)
            .headers(self.auth_headers());

        if let Some(body) = body {
            request = request.json(body);
        }

        let response = request
            .send()
            .await
            .map_err(|e| anyhow!("HTTP request failed: {}", e))?;

        let status = response.status();
        let response_text = response
            .text()
            .await
            .map_err(|e| anyhow!("Failed to read response text: {}", e))?;

        debug!("Response status: {}, body: {}", status, response_text);

        if !status.is_success() {
            return Err(anyhow!(
                "API request failed with status {}: {}",
                status,
                response_text
            ));
        }

        serde_json::from_str(&response_text).map_err(|e| {
            anyhow!(
                "Failed to parse JSON response: {}. Response: {}",
                e,
                response_text
            )
        })
    }

    async fn get_available_warehouse(&self) -> Result<String> {
        let url = format!("{}{}", self.host, SQL_WAREHOUSES_ENDPOINT);
        let response: WarehouseListResponse = self
            .api_request(reqwest::Method::GET, &url, None::<&()>)
            .await?;

        let running_warehouse = response
            .warehouses
            .into_iter()
            .find(|w| w.state == "RUNNING")
            .ok_or_else(|| anyhow!("No running SQL warehouse found"))?;

        info!(
            "Using warehouse: {} (ID: {})",
            running_warehouse.name.as_deref().unwrap_or("Unknown"),
            running_warehouse.id
        );

        Ok(running_warehouse.id)
    }

    pub async fn execute_sql(
        &self,
        request: &ExecuteSqlRequest,
    ) -> Result<ExecuteSqlResult> {
        let rows = self.execute_sql_impl(&request.query).await?;
        Ok(ExecuteSqlResult { rows })
    }

    async fn execute_sql_impl(&self, sql: &str) -> Result<Vec<HashMap<String, Value>>> {
        let warehouse_id = self.get_available_warehouse().await?;

        let request = SqlStatementRequest {
            statement: sql.to_string(),
            warehouse_id,
            catalog: None,
            schema: None,
            parameters: None,
            row_limit: Some(100),
            byte_limit: None,
            disposition: "INLINE".to_string(),
            format: "JSON_ARRAY".to_string(),
            wait_timeout: Some(DEFAULT_WAIT_TIMEOUT.to_string()),
            on_wait_timeout: Some("CONTINUE".to_string()),
        };

        let url = format!("{}{}", self.host, SQL_STATEMENTS_ENDPOINT);
        let response: SqlStatementResponse = self
            .api_request(reqwest::Method::POST, &url, Some(&request))
            .await?;

        // Check if we need to poll for results
        if let Some(status) = &response.status {
            if status.state == "PENDING" || status.state == "RUNNING" {
                return self.poll_for_results(&response.statement_id).await;
            } else if status.state == "FAILED" {
                let error_msg = status
                    .error
                    .as_ref()
                    .and_then(|e| e.message.as_ref())
                    .map(|m| m.as_str())
                    .unwrap_or("Unknown error");
                return Err(anyhow!("SQL execution failed: {}", error_msg));
            }
        }

        self.process_statement_result(&response)
    }

    async fn poll_for_results(&self, statement_id: &str) -> Result<Vec<HashMap<String, Value>>> {
        for attempt in 0..MAX_POLL_ATTEMPTS {
            debug!(
                "Polling attempt {} for statement {}",
                attempt + 1,
                statement_id
            );

            let url = format!("{}{}/{}", self.host, SQL_STATEMENTS_ENDPOINT, statement_id);
            let response: SqlStatementResponse = self
                .api_request(reqwest::Method::GET, &url, None::<&()>)
                .await?;

            if let Some(status) = &response.status {
                match status.state.as_str() {
                    "SUCCEEDED" => return self.process_statement_result(&response),
                    "FAILED" => {
                        let error_msg = status
                            .error
                            .as_ref()
                            .and_then(|e| e.message.as_ref())
                            .map(|m| m.as_str())
                            .unwrap_or("Unknown error");
                        return Err(anyhow!("SQL execution failed: {}", error_msg));
                    }
                    "PENDING" | "RUNNING" => {
                        sleep(Duration::from_secs(2)).await;
                        continue;
                    }
                    _ => return Err(anyhow!("Unexpected statement state: {}", status.state)),
                }
            }
        }

        Err(anyhow!(
            "Polling timeout exceeded for statement {}",
            statement_id
        ))
    }

    fn process_statement_result(
        &self,
        response: &SqlStatementResponse,
    ) -> Result<Vec<HashMap<String, Value>>> {
        debug!("Processing statement result: {:?}", response);

        let schema = response
            .manifest
            .as_ref()
            .and_then(|m| m.schema.as_ref())
            .ok_or_else(|| anyhow!("No schema in response"))?;

        // Try to get inline data
        if let Some(result) = &response.result
            && let Some(data_array) = &result.data_array {
                debug!("Found {} rows of inline data", data_array.len());
                return self.process_data_array(schema, data_array);
            }

        debug!(
            "Response structure: manifest={:?}, result={:?}",
            response.manifest, response.result
        );
        Err(anyhow!("No data found in response"))
    }

    fn process_data_array(
        &self,
        schema: &Schema,
        data_array: &[Vec<Option<String>>],
    ) -> Result<Vec<HashMap<String, Value>>> {
        let mut results = Vec::new();

        for row in data_array {
            let mut row_map = HashMap::new();

            for (i, column) in schema.columns.iter().enumerate() {
                let value = row
                    .get(i)
                    .and_then(|v| v.as_ref())
                    .map(|s| {
                        // Try to parse as number first, then as string
                        if let Ok(num) = s.parse::<f64>() {
                            Value::Number(
                                serde_json::Number::from_f64(num)
                                    .unwrap_or_else(|| serde_json::Number::from(0)),
                            )
                        } else {
                            Value::String(s.clone())
                        }
                    })
                    .unwrap_or(Value::Null);

                row_map.insert(column.name.clone(), value);
            }

            results.push(row_map);
        }

        Ok(results)
    }

    pub async fn list_catalogs(&self) -> Result<ListCatalogsResult> {
        let catalogs = self.list_catalogs_impl().await?;
        Ok(ListCatalogsResult { catalogs })
    }

    async fn list_catalogs_impl(&self) -> Result<Vec<String>> {
        let mut all_catalogs = Vec::new();
        let mut next_page_token: Option<String> = None;

        loop {
            let mut url = format!("{}{}", self.host, UNITY_CATALOG_CATALOGS_ENDPOINT);
            let mut query_params = Vec::new();

            if let Some(token) = &next_page_token {
                query_params.push(format!("page_token={}", urlencoding::encode(token)));
            }

            if !query_params.is_empty() {
                url.push('?');
                url.push_str(&query_params.join("&"));
            }

            let response: CatalogsListResponse = self
                .api_request(reqwest::Method::GET, &url, None::<&()>)
                .await?;

            if let Some(catalogs) = response.catalogs {
                for catalog in catalogs {
                    all_catalogs.push(catalog.name);
                }
            }

            if response.next_page_token.is_some() {
                next_page_token = response.next_page_token;
            } else {
                break;
            }
        }

        Ok(all_catalogs)
    }

    pub async fn list_schemas(
        &self,
        request: &ListSchemasRequest,
    ) -> Result<ListSchemasResult> {
        let mut schemas = self.list_schemas_impl(&request.catalog_name).await?;

        // Apply filter if provided
        if let Some(filter) = &request.filter {
            let filter_lower = filter.to_lowercase();
            schemas.retain(|s| s.to_lowercase().contains(&filter_lower));
        }

        let (schemas, total_count, shown_count) = apply_pagination(schemas, request.limit, request.offset);

        Ok(ListSchemasResult {
            schemas,
            total_count,
            shown_count,
            offset: request.offset,
            limit: request.limit,
        })
    }

    async fn list_schemas_impl(&self, catalog_name: &str) -> Result<Vec<String>> {
        let mut all_schemas = Vec::new();
        let mut next_page_token: Option<String> = None;

        loop {
            let mut url = format!("{}{}", self.host, UNITY_CATALOG_SCHEMAS_ENDPOINT);
            let mut query_params = vec![format!("catalog_name={}", urlencoding::encode(catalog_name))];

            if let Some(token) = &next_page_token {
                query_params.push(format!("page_token={}", urlencoding::encode(token)));
            }

            url.push('?');
            url.push_str(&query_params.join("&"));

            let response: SchemasListResponse = self
                .api_request(reqwest::Method::GET, &url, None::<&()>)
                .await?;

            if let Some(schemas) = response.schemas {
                for schema in schemas {
                    all_schemas.push(schema.name);
                }
            }

            if response.next_page_token.is_some() {
                next_page_token = response.next_page_token;
            } else {
                break;
            }
        }

        Ok(all_schemas)
    }

    pub async fn list_tables(&self, request: &ListTablesRequest) -> Result<ListTablesResult> {
        let tables = self.list_tables_impl(
            &request.catalog_name,
            &request.schema_name,
            request.exclude_inaccessible,
        )
        .await?;
        Ok(ListTablesResult { tables })
    }

    async fn list_tables_impl(
        &self,
        catalog_name: &str,
        schema_name: &str,
        exclude_inaccessible: bool,
    ) -> Result<Vec<TableInfo>> {
        let mut tables = Vec::new();
        let mut next_page_token: Option<String> = None;

        loop {
            let mut url = format!("{}{}", self.host, UNITY_CATALOG_TABLES_ENDPOINT);
            let mut query_params = vec![
                format!("catalog_name={}", urlencoding::encode(catalog_name)),
                format!("schema_name={}", urlencoding::encode(schema_name)),
            ];

            if exclude_inaccessible {
                query_params.push("include_browse=false".to_string());
            }

            if let Some(token) = &next_page_token {
                query_params.push(format!("page_token={}", urlencoding::encode(token)));
            }

            url.push('?');
            url.push_str(&query_params.join("&"));

            let response: TablesListResponse = self
                .api_request(reqwest::Method::GET, &url, None::<&()>)
                .await?;

            if let Some(table_list) = response.tables {
                for table in table_list {
                    tables.push(TableInfo {
                        name: table.name.clone(),
                        catalog_name: table.catalog_name.clone(),
                        schema_name: table.schema_name.clone(),
                        full_name: format!("{}.{}.{}", table.catalog_name, table.schema_name, table.name),
                        table_type: table.table_type.unwrap_or_else(|| "UNKNOWN".to_string()),
                        owner: table.owner,
                        comment: table.comment,
                    });
                }
            }

            if response.next_page_token.is_some() {
                next_page_token = response.next_page_token;
            } else {
                break;
            }
        }

        Ok(tables)
    }

    pub async fn describe_table(
        &self,
        request: &DescribeTableRequest,
    ) -> Result<TableDetails> {
        self.get_table_details_impl(&request.table_full_name, request.sample_size)
            .await
    }

    async fn get_table_details_impl(
        &self,
        table_name: &str,
        sample_rows: usize,
    ) -> Result<TableDetails> {
        // Get basic table metadata from Unity Catalog
        let url = format!(
            "{}{}/{}",
            self.host, UNITY_CATALOG_TABLES_ENDPOINT, table_name
        );
        let table_response: TableResponse = self
            .api_request(reqwest::Method::GET, &url, None::<&()>)
            .await?;

        // Build column metadata
        let columns = table_response
            .columns
            .unwrap_or_default()
            .into_iter()
            .map(|col| ColumnMetadata {
                name: col.name.unwrap_or_else(|| "unknown".to_string()),
                data_type: col.type_name.unwrap_or_else(|| "unknown".to_string()),
                comment: col.comment,
            })
            .collect();

        // Get sample data and row count
        let sample_data = if sample_rows > 0 {
            let sql = format!("SELECT * FROM {} LIMIT {}", table_name, sample_rows);
            self.execute_sql_impl(&sql).await.ok()
        } else {
            None
        };

        let row_count = {
            let sql = format!("SELECT COUNT(*) as count FROM {}", table_name);
            self.execute_sql_impl(&sql)
                .await
                .ok()
                .and_then(|results| results.first().cloned())
                .and_then(|row| row.get("count").cloned())
                .and_then(|value| match value {
                    Value::Number(n) => n.as_i64(),
                    Value::String(s) => s.parse().ok(),
                    _ => None,
                })
        };

        Ok(TableDetails {
            full_name: table_name.to_string(),
            table_type: table_response
                .table_type
                .unwrap_or_else(|| "UNKNOWN".to_string()),
            owner: table_response.owner,
            comment: table_response.comment,
            storage_location: table_response.storage_location,
            data_source_format: table_response.data_source_format,
            columns,
            sample_data,
            row_count,
        })
    }
}
