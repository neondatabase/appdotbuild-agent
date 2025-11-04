pub mod databricks;
pub mod deployment;
pub mod google_sheets;
pub mod io;
pub mod workspace;

pub use databricks::DatabricksProvider;
pub use deployment::DeploymentProvider;
pub use google_sheets::GoogleSheetsProvider;
pub use io::IOProvider;
pub use workspace::WorkspaceTools;

use crate::session::SessionContext;
use eyre::Result;
use rmcp::model::{
    CallToolRequestParam, CallToolResult, Implementation, PaginatedRequestParam, ProtocolVersion,
    ServerCapabilities, ServerInfo,
};
use rmcp::service::{RequestContext, RoleServer};
use rmcp::{ErrorData, ServerHandler};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Debug, PartialEq, Eq, Clone, Deserialize, Serialize)]
pub enum ProviderType {
    Databricks,
    Deployment,
    GoogleSheets,
    Io,
    Workspace,
}

enum TargetProvider {
    Databricks(Arc<DatabricksProvider>),
    Deployment(Arc<DeploymentProvider>),
    GoogleSheets(Arc<GoogleSheetsProvider>),
    Io(Arc<IOProvider>),
    Workspace(Arc<WorkspaceTools>),
}

#[derive(Clone)]
pub struct CombinedProvider {
    session_ctx: SessionContext,
    databricks: Option<Arc<DatabricksProvider>>,
    deployment: Option<Arc<DeploymentProvider>>,
    google_sheets: Option<Arc<GoogleSheetsProvider>>,
    io: Option<Arc<IOProvider>>,
    workspace: Option<Arc<WorkspaceTools>>,
}

impl CombinedProvider {
    pub fn new(
        session_ctx: SessionContext,
        databricks: Option<DatabricksProvider>,
        deployment: Option<DeploymentProvider>,
        google_sheets: Option<GoogleSheetsProvider>,
        io: Option<IOProvider>,
        workspace: Option<WorkspaceTools>,
    ) -> Result<Self> {
        if databricks.is_none()
            && deployment.is_none()
            && google_sheets.is_none()
            && io.is_none()
            && workspace.is_none()
        {
            return Err(eyre::eyre!("at least one provider must be available"));
        }
        Ok(Self {
            session_ctx,
            databricks: databricks.map(Arc::new),
            deployment: deployment.map(Arc::new),
            google_sheets: google_sheets.map(Arc::new),
            io: io.map(Arc::new),
            workspace: workspace.map(Arc::new),
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

        // check workspace tools
        if let Some(workspace) = self.workspace.clone() {
            if matches!(
                tool_name,
                "read_file" | "write_file" | "edit_file" | "bash" | "grep" | "glob"
            ) {
                return Ok(TargetProvider::Workspace(workspace));
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

    pub fn check_availability(&self, required: &[ProviderType]) -> Result<()> {
        for provider in required {
            match provider {
                ProviderType::Databricks => {
                    if self.databricks.is_none() {
                        return Err(eyre::eyre!(
                            "Databricks provider is required but not configured. Environment variables DATABRICKS_HOST, DATABRICKS_TOKEN, DATABRICKS_WAREHOUSE_ID must be set."
                        ));
                    }
                }
                ProviderType::Deployment => {
                    if self.deployment.is_none() {
                        return Err(eyre::eyre!(
                            "Deployment provider is required but not configured."
                        ));
                    }
                }
                ProviderType::GoogleSheets => {
                    if self.google_sheets.is_none() {
                        return Err(eyre::eyre!(
                            "Google Sheets provider is required but not configured."
                        ));
                    }
                }
                ProviderType::Io => {
                    if self.io.is_none() {
                        return Err(eyre::eyre!("I/O provider is required but not configured."));
                    }
                }
                ProviderType::Workspace => {
                    if self.workspace.is_none() {
                        return Err(eyre::eyre!(
                            "Workspace provider is required but not configured."
                        ));
                    }
                }
            }
        }
        Ok(())
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
        if self.workspace.is_some() {
            providers.push("Workspace");
        }

        ServerInfo {
            protocol_version: ProtocolVersion::V_2024_11_05,
            capabilities: ServerCapabilities::builder().enable_tools().build(),
            server_info: Implementation {
                name: "edda-mcp".to_string(),
                version: env!("CARGO_PKG_VERSION").to_string(),
                title: Some("Edda MCP Server".to_string()),
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
        // check if this is the first tool call in the session
        let is_first_call = {
            let mut first_call_lock = self.session_ctx.first_tool_called.write().await;
            let is_first = !*first_call_lock;
            if is_first {
                *first_call_lock = true;
            }
            is_first
        };

        // intercept scaffold_data_app to set work_dir in session context
        if params.name == "scaffold_data_app" {
            if let Some(ref io) = self.io {
                let result = io.call_tool(params.clone(), context.clone()).await?;

                // extract work_dir from arguments and set it in session context
                if let Some(args) = params.arguments {
                    if let Some(work_dir) = args.get("work_dir").and_then(|v| v.as_str()) {
                        let path = std::path::PathBuf::from(work_dir);

                        // validate path exists and is directory
                        if path.exists() && path.is_dir() {
                            let mut work_dir_lock = self.session_ctx.work_dir.write().await;
                            if work_dir_lock.is_none() {
                                *work_dir_lock = Some(path);
                            }
                        }
                    }
                }

                return Ok(result);
            }
        }

        let mut result = match self.resolve_provider(&params.name)? {
            TargetProvider::Databricks(provider) => provider.call_tool(params, context).await,
            TargetProvider::Deployment(provider) => provider.call_tool(params, context).await,
            TargetProvider::GoogleSheets(provider) => provider.call_tool(params, context).await,
            TargetProvider::Io(provider) => provider.call_tool(params, context).await,
            TargetProvider::Workspace(provider) => provider.call_tool(params, context).await,
        }?;

        // inject engine guide on first tool call
        if is_first_call {
            use crate::engine_guide::ENGINE_GUIDE;
            use rmcp::model::RawContent;

            // prepend engine guide to the first content item
            if let Some(first_content) = result.content.first_mut() {
                if let RawContent::Text(text_content) = &mut first_content.raw {
                    text_content.text = format!("{}\n\n---\n\n{}", ENGINE_GUIDE, text_content.text);
                }
            }
        }

        Ok(result)
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
            if let Ok(result) = google_sheets
                .list_tools(params.clone(), context.clone())
                .await
            {
                tools.extend(result.tools);
            }
        }

        if let Some(ref io) = self.io {
            if let Ok(result) = io.list_tools(params.clone(), context.clone()).await {
                tools.extend(result.tools);
            }
        }

        if let Some(ref workspace) = self.workspace {
            if let Ok(result) = workspace.list_tools(params.clone(), context.clone()).await {
                tools.extend(result.tools);
            }
        }

        Ok(rmcp::model::ListToolsResult {
            tools,
            next_cursor: None,
        })
    }
}
