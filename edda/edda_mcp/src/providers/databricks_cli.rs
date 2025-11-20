use edda_integrations::{
    DatabricksRestClient, DescribeTableRequest, ExecuteSqlRequest, ToolResultDisplay,
};
use eyre::Result;
use rmcp::handler::server::router::tool::ToolRouter;
use rmcp::handler::server::wrapper::Parameters;
use rmcp::model::{CallToolResult, Content, ServerInfo};
use rmcp::{tool, tool_handler, tool_router, ErrorData, ServerHandler};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Debug, Deserialize, Serialize, JsonSchema)]
pub struct DatabricksCliArgs {
    /// Arguments to pass to databricks CLI (e.g., "unity-catalog catalogs list --output json")
    pub args: String,
}

/// Provider for Databricks CLI operations
#[derive(Clone)]
pub struct DatabricksCliProvider {
    rest_client: Arc<DatabricksRestClient>,
    tool_router: ToolRouter<Self>,
}

#[tool_router]
impl DatabricksCliProvider {
    pub fn new() -> Result<Self> {
        let rest_client = DatabricksRestClient::new()
            .map_err(|e| eyre::eyre!("Failed to create Databricks REST client: {}", e))?;
        Ok(Self {
            rest_client: Arc::new(rest_client),
            tool_router: Self::tool_router(),
        })
    }

    #[tool(
        name = "run_databricks_cli",
        description = "Execute Databricks CLI command for accessing Databricks data. Pass all arguments as a single string.\
\nAuthentication: Set DATABRICKS_HOST, DATABRICKS_TOKEN, DATABRICKS_WAREHOUSE_ID env vars.\
\n## ⚡ EFFICIENT WORKFLOW (Recommended):\
1. 'catalogs list' → find available catalogs\
2. 'schemas list CATALOG' → find schemas in catalog\
3. 'tables list CATALOG SCHEMA' → find tables in schema\
4. 'discover_schema TABLE1 TABLE2 TABLE3' → **BATCH discover multiple tables in ONE call** ⚡\
\n## Commands:\
- Execute SQL: 'query \"SELECT * FROM table LIMIT 5\"' (returns data + row count)\
- Discover schema: 'discover_schema TABLE1 TABLE2 ...' (columns, types, samples, nulls, counts)\
  ↳ ALWAYS use batch mode: 'discover_schema tbl1 tbl2 tbl3' instead of 3 separate calls\
- Get help: 'tables --help'\
\n## Common Errors:\
❌ 'tables list samples.tpcds_sf1' → Wrong format!\
✅ 'tables list samples tpcds_sf1' → Correct (CATALOG SCHEMA as separate args)\
\n**Best Practices**:\
✅ Use batch discover_schema for multiple tables (faster)\
✅ Always test SQL with 'query' command before implementing in backend code"
    )]
    pub async fn run_databricks_cli(
        &self,
        Parameters(args): Parameters<DatabricksCliArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let args_vec: Vec<&str> = args.args.split_whitespace().collect();

        if args_vec.is_empty() {
            return Err(ErrorData::invalid_params(
                "Command requires at least one argument",
                None,
            ));
        }

        let command = args_vec[0];
        let mut remaining_args_vec: Vec<String> =
            args_vec[1..].iter().map(|s| s.to_string()).collect();

        // Auto-parse dot notation to separate args for CLI commands
        // e.g., "tables list samples.tpcds_sf1" → "tables list samples tpcds_sf1"
        if matches!(command, "tables" | "schemas")
            && remaining_args_vec.len() == 2
            && remaining_args_vec[0] == "list"
        {
            let dotted = remaining_args_vec[1].clone();
            if dotted.contains('.') {
                let parts: Vec<String> = dotted.split('.').map(|s| s.to_string()).collect();
                remaining_args_vec.truncate(1); // keep "list"
                remaining_args_vec.extend(parts);
            }
        }

        let remaining_args: Vec<&str> = remaining_args_vec.iter().map(|s| s.as_str()).collect();

        match command {
            "query" => self.handle_query(remaining_args).await,
            "discover_schema" => self.handle_discover_schema(remaining_args).await,
            _ => self.handle_cli_fallback(command, remaining_args).await,
        }
    }

    async fn handle_query(&self, args: Vec<&str>) -> Result<CallToolResult, ErrorData> {
        if args.is_empty() {
            return Err(ErrorData::invalid_params(
                "query command requires SQL statement",
                None,
            ));
        }

        let query = args.join(" ");
        // strip surrounding quotes if present
        let query = query
            .trim()
            .trim_start_matches('"')
            .trim_end_matches('"')
            .lines()
            .map(|line| line.trim())
            .filter(|line| !line.is_empty() && !line.trim_start().starts_with("--"))
            .collect::<Vec<_>>()
            .join(" ")
            .to_string();

        let request = ExecuteSqlRequest { query };

        match self.rest_client.execute_sql(&request).await {
            Ok(result) => {
                let row_count = result.rows.len();
                let output = format!(
                    "{}\n\n--- Query Statistics ---\nRows returned: {}",
                    result.display(),
                    row_count
                );
                Ok(CallToolResult::success(vec![Content::text(output)]))
            }
            Err(e) => {
                let error_msg = format!("Failed to execute SQL query: {}", e);
                let hint = if error_msg.contains("PARSE_SYNTAX_ERROR")
                    || error_msg.contains("ParseException")
                {
                    "\n\n💡 Databricks SQL syntax tips:\
• Use DATE_SUB(col, 90) not col - INTERVAL 90 DAYS\
• Use DATE_ADD(col, 7) not col + INTERVAL 7 DAYS\
• Use CONCAT() not || for string concatenation\
• Backtick special column names: `column name`"
                } else {
                    ""
                };
                Err(ErrorData::internal_error(
                    format!("{}{}", error_msg, hint),
                    None,
                ))
            }
        }
    }

    async fn handle_discover_schema(&self, tables: Vec<&str>) -> Result<CallToolResult, ErrorData> {
        if tables.is_empty() {
            return Err(ErrorData::invalid_params(
                "discover_schema command requires at least one table name (format: CATALOG.SCHEMA.TABLE). Multiple tables can be provided for batch discovery.",
                None,
            ));
        }

        let mut all_results = Vec::new();
        let remaining_args_count = tables.len();

        for table_name in tables {
            // validate format
            let parts: Vec<&str> = table_name.split('.').collect();
            if parts.len() != 3 {
                all_results.push(format!(
                    "❌ {}: Invalid format (expected CATALOG.SCHEMA.TABLE)",
                    table_name
                ));
                continue;
            }

            let mut output_sections = Vec::new();
            if remaining_args_count > 1 {
                output_sections.push(format!(
                    "\n{}
{}
{}",
                    "=".repeat(70),
                    table_name,
                    "=".repeat(70)
                ));
            }

            // 1. Describe table (Metadata, Samples, Row Count)
            // This replaces 3 separate SQL calls (DESCRIBE, SELECT * LIMIT 5, COUNT(*))
            let description = match self
                .rest_client
                .describe_table(&DescribeTableRequest {
                    table_full_name: table_name.to_string(),
                    sample_size: 5,
                })
                .await
            {
                Ok(details) => details,
                Err(e) => {
                    all_results.push(format!(
                        "{}\nFailed to describe table: {}",
                        output_sections.join("\n"),
                        e
                    ));
                    continue;
                }
            };

            output_sections.push(description.display());

            // 2. Null counts (still needs a custom query)
            let column_names: Vec<String> = description
                .columns
                .iter()
                .filter(|col| {
                    // Filter out obvious metadata columns if any, though Unity Catalog columns are usually clean.
                    // Keeping safety checks just in case.
                    !col.name.starts_with('#')
                        && !col.name.is_empty()
                        && col.name != "Partition Information"
                        && col.name != "Detailed Table Information"
                })
                .map(|c| c.name.clone())
                .collect();

            if !column_names.is_empty() {
                let null_checks: Vec<String> = column_names
                    .iter()
                    .map(|col| {
                        format!(
                            "COUNT(CASE WHEN `{}` IS NULL THEN 1 END) as `{}_nulls`",
                            col,
                            col
                        )
                    })
                    .collect();

                let null_query = format!("SELECT {} FROM {}", null_checks.join(", "), table_name);
                match self
                    .rest_client
                    .execute_sql(&ExecuteSqlRequest { query: null_query })
                    .await
                {
                    Ok(result) => {
                        output_sections.push(format!(
                            "\n=== Null Counts by Column ===\n{}",
                            result.display()
                        ));
                    }
                    Err(e) => {
                        output_sections.push(format!("\n=== Null Counts ===\nFailed to analyze: {}", e));
                    }
                }
            }

            all_results.push(output_sections.join("\n"));
        }

        Ok(CallToolResult::success(vec![Content::text(
            all_results.join("\n\n"),
        )]))
    }

    async fn handle_cli_fallback(
        &self,
        command: &str,
        args: Vec<&str>,
    ) -> Result<CallToolResult, ErrorData> {
        let output = tokio::process::Command::new("databricks")
            .arg(command)
            .args(args)
            .output()
            .await
            .map_err(|e| {
                ErrorData::internal_error(
                    format!("Failed to execute databricks command: {}", e),
                    None,
                )
            })?;

        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();

        if output.status.success() {
            let result = if !stderr.is_empty() {
                format!("{}\n\nWarnings/Info:\n{}", stdout, stderr)
            } else {
                stdout
            };
            Ok(CallToolResult::success(vec![Content::text(result)]))
        } else {
            let error_msg = format!(
                "databricks CLI command failed (exit code: {})\n\nStdout:\n{}\n\nStderr:\n{}",
                output.status.code().unwrap_or(-1),
                stdout,
                stderr
            );
            Err(ErrorData::internal_error(error_msg, None))
        }
    }
}

#[tool_handler]
impl ServerHandler for DatabricksCliProvider {
    fn get_info(&self) -> ServerInfo {
        crate::mcp_helpers::internal_server_info()
    }
}
