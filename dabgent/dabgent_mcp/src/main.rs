use dabgent_mcp::providers::{
    CombinedProvider, DatabricksProvider, DeploymentProvider, GoogleSheetsProvider, IOProvider,
};
use eyre::Result;
use rmcp::ServiceExt;
use rmcp::transport::stdio;
use tracing_subscriber;

#[tokio::main]
async fn main() -> Result<()> {
    // configure tracing to write to stderr only if RUST_LOG is set
    // this prevents interference with stdio MCP transport
    if std::env::var("RUST_LOG").is_ok() {
        // write to a file to avoid interfering with stdio
        let log_file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open("/tmp/dabgent-mcp.log")?;

        tracing_subscriber::fmt()
            .with_writer(move || log_file.try_clone().unwrap())
            .init();
    }

    // initialize all available providers
    let databricks = DatabricksProvider::new().ok();
    let deployment = DeploymentProvider::new().ok();
    let google_sheets = GoogleSheetsProvider::new().await.ok();
    let io = IOProvider::new().ok();

    // create combined provider with all available integrations
    let provider =
        CombinedProvider::new(databricks, deployment, google_sheets, io).map_err(|_| {
            eyre::eyre!(
                "No integrations available. Configure at least one:\n\
             - Databricks: Set DATABRICKS_HOST and DATABRICKS_TOKEN\n\
             - Deployment: Set DATABRICKS_HOST and DATABRICKS_TOKEN)\n\
             - Google Sheets: Place credentials at ~/.config/gspread/credentials.json\n\
             - I/O: Always available"
            )
        })?;

    let service = provider.serve(stdio()).await?;
    service.waiting().await?;
    Ok(())
}
