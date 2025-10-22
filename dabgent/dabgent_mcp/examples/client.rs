//! Example MCP client that connects to the dabgent-mcp server in-process
//!
//! This demonstrates how to:
//! - Create provider instances directly
//! - Connect to them in-process using rmcp-in-process-transport
//! - Call tools exposed by the server
//!
//! Run with: cargo run --example client

use dabgent_mcp::providers::{
    CombinedProvider, DatabricksProvider, DeploymentProvider, GoogleSheetsProvider, IOProvider,
};
use eyre::Result;
use rmcp::ServiceExt;
use rmcp::model::CallToolRequestParam;
use rmcp_in_process_transport::in_process::TokioInProcess;

#[tokio::main]
async fn main() -> Result<()> {
    // optionally initialize logging if RUST_LOG is set
    if std::env::var("RUST_LOG").is_ok() {
        tracing_subscriber::fmt::init();
    }

    println!("Starting dabgent-mcp server in-process...");

    // initialize providers
    let databricks = DatabricksProvider::new().ok();
    let deployment = DeploymentProvider::new().ok();
    let google_sheets = GoogleSheetsProvider::new().await.ok();
    let io = IOProvider::new().ok();

    let provider =
        CombinedProvider::new(databricks, deployment, google_sheets, io).map_err(|_| {
            eyre::eyre!(
                "No integrations available. Configure at least one:\n\
             - Databricks: Set DATABRICKS_HOST and DATABRICKS_TOKEN\n\
             - Google Sheets: Place credentials at ~/.config/gspread/credentials.json\n\
             - I/O: Always available"
            )
        })?;

    // create in-process service
    let tokio_in_process = TokioInProcess::new(provider).await?;
    let service = ().serve(tokio_in_process).await?;

    println!("Connected to server!\n");

    // get server info
    let server_info = service.peer_info();
    if let Some(info) = server_info {
        println!(
            "Server: {} v{}",
            info.server_info.name, info.server_info.version
        );
        if let Some(instructions) = &info.instructions {
            println!("Description: {}", instructions);
        }
        println!();
    }

    // list available tools
    println!("=== Listing available tools ===");
    let tools_response = service.list_tools(Default::default()).await?;
    for tool in &tools_response.tools {
        let desc = tool
            .description
            .as_ref()
            .map(|d| d.as_ref())
            .unwrap_or("No description");
        println!("- {}: {}", tool.name, desc);
    }
    println!();

    // example 1: call a Databricks tool (if available)
    if tools_response
        .tools
        .iter()
        .any(|t| t.name == "databricks_list_catalogs")
    {
        println!("=== Example: Listing Databricks catalogs ===");
        let result = service
            .call_tool(CallToolRequestParam {
                name: "databricks_list_catalogs".into(),
                arguments: None,
            })
            .await?;

        // extract and display text content
        if let Some(content) = result.content.first() {
            if let Some(text) = content.as_text() {
                println!("{}", text.text);
            }
        }
        println!();
    }

    println!("Example complete!");

    // cleanup
    service.cancel().await?;

    Ok(())
}
