use edda_integrations::{
    FetchSpreadsheetDataRequest, GetSpreadsheetMetadataRequest, GoogleSheetsClient,
    ReadRangeRequest, ToolResultDisplay,
};
use eyre::Result;
use rmcp::handler::server::router::tool::ToolRouter;
use rmcp::handler::server::wrapper::Parameters;
use rmcp::model::{CallToolResult, Content, ServerInfo};
use rmcp::{tool, tool_handler, tool_router, ErrorData, ServerHandler};
use std::sync::Arc;

#[derive(Clone)]
pub struct GoogleSheetsProvider {
    client: Arc<GoogleSheetsClient>,
    tool_router: ToolRouter<Self>,
}

#[tool_router]
impl GoogleSheetsProvider {
    pub async fn new() -> Result<Self> {
        let client = GoogleSheetsClient::new()
            .await
            .map_err(|e| eyre::eyre!("Failed to create Google Sheets client: {}", e))?;
        Ok(Self {
            client: Arc::new(client),
            tool_router: Self::tool_router(),
        })
    }

    #[tool(name = "google_sheets_get_metadata", description = "Get metadata for a Google Sheets spreadsheet")]
    pub async fn get_metadata(
        &self,
        Parameters(args): Parameters<GetSpreadsheetMetadataRequest>,
    ) -> Result<CallToolResult, ErrorData> {
        match self.client.get_spreadsheet_metadata(&args).await {
            Ok(result) => Ok(CallToolResult::success(vec![Content::text(result.display())])),
            Err(e) => Err(ErrorData::internal_error(e.to_string(), None)),
        }
    }

    #[tool(name = "google_sheets_read_range", description = "Read a specific range from a Google Sheets spreadsheet")]
    pub async fn read_range(
        &self,
        Parameters(args): Parameters<ReadRangeRequest>,
    ) -> Result<CallToolResult, ErrorData> {
        match self.client.read_range(&args).await {
            Ok(result) => Ok(CallToolResult::success(vec![Content::text(result.display())])),
            Err(e) => Err(ErrorData::internal_error(e.to_string(), None)),
        }
    }

    #[tool(name = "google_sheets_fetch_full", description = "Fetch all data from a Google Sheets spreadsheet")]
    pub async fn fetch_full(
        &self,
        Parameters(args): Parameters<FetchSpreadsheetDataRequest>,
    ) -> Result<CallToolResult, ErrorData> {
        match self.client.fetch_spreadsheet_data(&args).await {
            Ok(result) => Ok(CallToolResult::success(vec![Content::text(result.display())])),
            Err(e) => Err(ErrorData::internal_error(e.to_string(), None)),
        }
    }
}

#[tool_handler]
impl ServerHandler for GoogleSheetsProvider {
    fn get_info(&self) -> ServerInfo {
        crate::mcp_helpers::internal_server_info()
    }
}
