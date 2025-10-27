use dabgent_mcp::providers::{
    CombinedProvider, DatabricksProvider, DeploymentProvider, IOProvider, GoogleSheetsProvider,
};
use dabgent_sandbox::dagger::{ConnectOpts, Logger};
use dabgent_sandbox::{DaggerSandbox, Sandbox};
use eyre::Result;
use rmcp::ServiceExt;
use rmcp::transport::stdio;
use tracing_subscriber;

/// check if docker is available by running 'docker ps'
async fn check_docker_available() -> Result<()> {
    let output = tokio::process::Command::new("docker")
        .arg("ps")
        .output()
        .await;

    match output {
        Ok(output) if output.status.success() => Ok(()),
        Ok(_) => Err(eyre::eyre!(
            "docker command found but not responding (is the daemon running?)"
        )),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            Err(eyre::eyre!("docker command not found"))
        }
        Err(e) => Err(eyre::eyre!("failed to check docker: {}", e)),
    }
}

/// warmup sandbox by pre-pulling node image and creating a test container
async fn warmup_sandbox() -> Result<()> {
    let opts = ConnectOpts::default()
        .with_logger(Logger::Silent)
        .with_execute_timeout(Some(600));

    opts.connect(|client| async move {
        let container = client
            .container()
            .from("node:20-alpine3.22")
            .with_exec(vec!["mkdir", "-p", "/app"]);
        let sandbox = DaggerSandbox::from_container(container, client);
        // force evaluation to ensure image is pulled
        let _ = sandbox.list_directory("/app").await?;
        Ok(())
    })
    .await
    .map_err(|e| eyre::eyre!("dagger connect failed: {}", e))?;

    Ok(())
}

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

    // check if docker is available before initializing providers
    let docker_available = check_docker_available().await.is_ok();
    if !docker_available {
        eprintln!("⚠️  Warning: docker not available - you may have issues with sandbox operations\n");
    }

    // spawn non-blocking warmup task if docker is available
    if docker_available {
        tokio::spawn(async {
            if let Err(e) = warmup_sandbox().await {
                eprintln!("⚠️  Sandbox warmup failed: {}", e);
            }
        });
    }

    // initialize all available providers
    let databricks = DatabricksProvider::new().ok();
    let deployment = DeploymentProvider::new().ok();
    let google_sheets = GoogleSheetsProvider::new().await.ok();
    let io = IOProvider::new().ok();

    // print startup banner to stderr (won't interfere with stdio MCP transport)
    let mut providers_list = Vec::new();
    if databricks.is_some() {
        providers_list.push("Databricks");
    }
    if deployment.is_some() {
        providers_list.push("Deployment");
    }
    if google_sheets.is_some() {
        providers_list.push("Google Sheets");
    }
    if io.is_some() {
        providers_list.push("I/O");
    }

    eprintln!(
        "🚀 Dabgent MCP Server v{} - build data apps deployable on Databricks Apps platform \n\
         Configured providers: {}\n\
         Got questions? eng-appbuild@databricks.com\n\
         Server running on stdio transport...",
        env!("CARGO_PKG_VERSION"),
        providers_list.join(", ")
    );

    // create combined provider with all available integrations
    let provider = CombinedProvider::new(databricks, deployment, google_sheets, io).map_err(
        |_| {
            eyre::eyre!(
                "No integrations available. Configure at least one:\n\
             - Databricks: Set DATABRICKS_HOST and DATABRICKS_TOKEN\n\
             - Deployment: Set DATABRICKS_HOST and DATABRICKS_TOKEN)\n\
             - Google Sheets: Place credentials at ~/.config/gspread/credentials.json\n\
             - I/O: Always available"
            )
        },
    )?;

    let service = provider.serve(stdio()).await?;
    service.waiting().await?;
    Ok(())
}
