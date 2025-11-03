use anyhow::{Context, Result};
use mcp_client_rs::client::{Client, ClientBuilder};
use serde::{Deserialize, Serialize};
use tracing::info;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tool {
    pub name: String,
    pub description: Option<String>,
    #[serde(rename = "inputSchema")]
    pub input_schema: serde_json::Value,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ListToolsResult {
    pub tools: Vec<Tool>,
}

pub struct McpClient {
    client: Client,
}

impl std::fmt::Debug for McpClient {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("McpClient").finish()
    }
}

impl McpClient {
    pub async fn spawn(binary_path: &str) -> Result<Self> {
        info!("Spawning MCP server: {}", binary_path);

        let client = ClientBuilder::new(binary_path)
            .spawn_and_initialize()
            .await
            .context("Failed to spawn and initialize MCP client")?;

        info!("MCP client initialized successfully");

        Ok(Self { client })
    }

    pub async fn list_tools(&self) -> Result<Vec<Tool>> {
        let response_value = self.client
            .request("tools/list", Some(serde_json::json!({})))
            .await
            .context("Failed to list tools")?;

        let response: ListToolsResult = serde_json::from_value(response_value)
            .context("Failed to parse tools list response")?;

        Ok(response.tools)
    }
}
