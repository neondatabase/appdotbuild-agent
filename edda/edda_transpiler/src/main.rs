use edda_transpiler::providers::transpiler::TranspilerProvider;
use eyre::Result;
use rmcp::ServiceExt;
use rmcp::transport::stdio;

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize tracing to stderr (won't interfere with stdio MCP transport)
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .init();

    tracing::info!("Starting edda_transpiler MCP server");

    // Create provider
    let provider = TranspilerProvider::new()?;

    // Start server with stdio transport
    let service = provider.serve(stdio()).await?;
    service.waiting().await?;

    Ok(())
}
