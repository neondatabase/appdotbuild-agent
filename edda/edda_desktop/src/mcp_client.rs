use anyhow::{Context, Result};
use mcp_client_rs::client::{Client, ClientBuilder};
use rig::completion::ToolDefinition;
use serde::{Deserialize, Serialize};
use tracing::info;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tool {
    pub name: String,
    pub description: Option<String>,
    #[serde(rename = "inputSchema")]
    pub input_schema: serde_json::Value,
}

impl Tool {
    // convert MCP tool to Rig ToolDefinition
    pub fn to_rig_definition(&self) -> ToolDefinition {
        ToolDefinition {
            name: self.name.clone(),
            description: self.description.clone().unwrap_or_default(),
            parameters: self.input_schema.clone(),
        }
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ListToolsResult {
    pub tools: Vec<Tool>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CallToolResult {
    pub content: Vec<CallToolContent>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum CallToolContent {
    #[serde(rename = "text")]
    Text { text: String },
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
        let response_value = self
            .client
            .request("tools/list", Some(serde_json::json!({})))
            .await
            .context("Failed to list tools")?;

        let response: ListToolsResult = serde_json::from_value(response_value)
            .context("Failed to parse tools list response")?;

        Ok(response.tools)
    }

    pub async fn call_tool(&self, name: &str, arguments: serde_json::Value) -> Result<String> {
        let request = serde_json::json!({
            "name": name,
            "arguments": arguments,
        });

        let response_value = self
            .client
            .request("tools/call", Some(request))
            .await
            .context(format!("Failed to call tool: {}", name))?;

        let response: CallToolResult = serde_json::from_value(response_value)
            .context("Failed to parse tool call response")?;

        // extract text content from response
        let text_content = response
            .content
            .into_iter()
            .filter_map(|content| match content {
                CallToolContent::Text { text } => Some(text),
            })
            .collect::<Vec<_>>()
            .join("\n");

        Ok(text_content)
    }
}
