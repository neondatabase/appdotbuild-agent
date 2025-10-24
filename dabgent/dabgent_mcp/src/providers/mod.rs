pub mod databricks;
pub mod deployment;
pub mod io;
pub mod google_sheets;

pub use databricks::DatabricksProvider;
pub use deployment::DeploymentProvider;
pub use io::{IOProvider, Template};
pub use google_sheets::GoogleSheetsProvider;

use eyre::Result;
use rmcp::model::{
    CallToolRequestParam, CallToolResult, Implementation, PaginatedRequestParam, ProtocolVersion,
    ServerCapabilities, ServerInfo,
};
use rmcp::service::{RequestContext, RoleServer};
use rmcp::{ErrorData, ServerHandler};
use std::sync::Arc;

enum TargetProvider {
    Databricks(Arc<DatabricksProvider>),
    Deployment(Arc<DeploymentProvider>),
    GoogleSheets(Arc<GoogleSheetsProvider>),
    Io(Arc<IOProvider>),
}

#[derive(Clone)]
pub struct CombinedProvider {
    databricks: Option<Arc<DatabricksProvider>>,
    deployment: Option<Arc<DeploymentProvider>>,
    google_sheets: Option<Arc<GoogleSheetsProvider>>,
    io: Option<Arc<IOProvider>>,
}

impl CombinedProvider {
    pub fn new(
        databricks: Option<DatabricksProvider>,
        deployment: Option<DeploymentProvider>,
        google_sheets: Option<GoogleSheetsProvider>,
        io: Option<IOProvider>,
    ) -> Result<Self> {
        if databricks.is_none()
            && deployment.is_none()
            && google_sheets.is_none()
            && io.is_none()
        {
            return Err(eyre::eyre!("at least one provider must be available"));
        }
        Ok(Self {
            databricks: databricks.map(Arc::new),
            deployment: deployment.map(Arc::new),
            google_sheets: google_sheets.map(Arc::new),
            io: io.map(Arc::new),
        })
    }

    fn resolve_provider(&self, tool_name: &str) -> std::result::Result<TargetProvider, ErrorData> {
        if tool_name.starts_with("databricks_") {
            let provider = self.databricks.clone().ok_or_else(|| {
                ErrorData::invalid_params(
                    "Databricks provider not configured. Set DATABRICKS_HOST and DATABRICKS_TOKEN.",
                    None,
                )
            })?;
            return Ok(TargetProvider::Databricks(provider));
        }

        if tool_name.starts_with("google_sheets_") {
            let provider = self.google_sheets.clone().ok_or_else(|| {
                ErrorData::invalid_params(
                    "Google Sheets provider not configured. Provide credentials at ~/.config/gspread/credentials.json.",
                    None,
                )
            })?;
            return Ok(TargetProvider::GoogleSheets(provider));
        }

        if let Some(deployment) = self.deployment.clone() {
            match tool_name {
                "deploy_databricks_app" => {
                    return Ok(TargetProvider::Deployment(deployment));
                }
                _ => {}
            }
        }

        if let Some(io) = self.io.clone() {
            match tool_name {
                "scaffold_data_app" | "validate_data_app" => {
                    return Ok(TargetProvider::Io(io));
                }
                _ => {}
            }
        }

        let mut configured = Vec::new();
        if let Some(provider) = &self.databricks {
            configured.push(TargetProvider::Databricks(Arc::clone(provider)));
        }
        if let Some(provider) = &self.deployment {
            configured.push(TargetProvider::Deployment(Arc::clone(provider)));
        }
        if let Some(provider) = &self.google_sheets {
            configured.push(TargetProvider::GoogleSheets(Arc::clone(provider)));
        }
        if let Some(provider) = &self.io {
            configured.push(TargetProvider::Io(Arc::clone(provider)));
        }

        if configured.len() == 1 {
            return Ok(configured.into_iter().next().unwrap());
        }

        Err(ErrorData::invalid_params(
            format!("unknown tool: {}", tool_name),
            None,
        ))
    }
}

impl ServerHandler for CombinedProvider {
    fn get_info(&self) -> ServerInfo {
        let mut providers = Vec::new();
        if self.databricks.is_some() {
            providers.push("Databricks");
        }
        if self.deployment.is_some() {
            providers.push("Deployment");
        }
        if self.google_sheets.is_some() {
            providers.push("Google Sheets");
        }
        if self.io.is_some() {
            providers.push("I/O");
        }

        ServerInfo {
            protocol_version: ProtocolVersion::V_2024_11_05,
            capabilities: ServerCapabilities::builder().enable_tools().build(),
            server_info: Implementation {
                name: "dabgent-mcp".to_string(),
                version: env!("CARGO_PKG_VERSION").to_string(),
                title: Some("Dabgent MCP Server".to_string()),
                website_url: None,
                icons: None,
            },
            instructions: Some(format!(
                "MCP server providing integrations for: {}",
                providers.join(", ")
            )),
        }
    }

    async fn call_tool(
        &self,
        params: CallToolRequestParam,
        context: RequestContext<RoleServer>,
    ) -> std::result::Result<CallToolResult, ErrorData> {
        match self.resolve_provider(&params.name)? {
            TargetProvider::Databricks(provider) => provider.call_tool(params, context).await,
            TargetProvider::Deployment(provider) => provider.call_tool(params, context).await,
            TargetProvider::GoogleSheets(provider) => provider.call_tool(params, context).await,
            TargetProvider::Io(provider) => provider.call_tool(params, context).await,
        }
    }

    async fn list_tools(
        &self,
        params: Option<PaginatedRequestParam>,
        context: RequestContext<RoleServer>,
    ) -> std::result::Result<rmcp::model::ListToolsResult, ErrorData> {
        let mut tools = Vec::new();

        if let Some(ref databricks) = self.databricks {
            if let Ok(result) = databricks.list_tools(params.clone(), context.clone()).await {
                tools.extend(result.tools);
            }
        }

        if let Some(ref deployment) = self.deployment {
            if let Ok(result) = deployment.list_tools(params.clone(), context.clone()).await {
                tools.extend(result.tools);
            }
        }

        if let Some(ref google_sheets) = self.google_sheets {
            if let Ok(result) = google_sheets.list_tools(params.clone(), context.clone()).await {
                tools.extend(result.tools);
            }
        }

        if let Some(ref io) = self.io {
            if let Ok(result) = io.list_tools(params.clone(), context.clone()).await {
                tools.extend(result.tools);
            }
        }

        Ok(rmcp::model::ListToolsResult {
            tools,
            next_cursor: None,
        })
    }
}
