use clap::{Parser, Subcommand};
use edda_mcp::paths;
use edda_mcp::providers::{
    CombinedProvider, DatabricksProvider, DeploymentProvider, GoogleSheetsProvider, IOProvider,
};
use edda_mcp::trajectory::TrajectoryTrackingProvider;
use edda_mcp::yell;
use edda_sandbox::dagger::{ConnectOpts, Logger};
use edda_sandbox::{DaggerSandbox, Sandbox};
use eyre::Result;
use rmcp::ServiceExt;
use rmcp::transport::stdio;
use tracing_subscriber;
use uuid::Uuid;

#[derive(Parser)]
#[command(name = "edda_mcp")]
#[command(about = "Edda MCP Server", long_about = None)]
struct Cli {
    /// Disallow deployment operations (overrides config file)
    #[arg(long)]
    disallow_deployment: bool,

    #[command(subcommand)]
    command: Option<Commands>,
}

#[derive(Subcommand)]
enum Commands {
    /// Report a bug and bundle diagnostic data
    Yell {
        /// Bug description (optional, will prompt if not provided)
        message: Option<String>,
    },
}

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
    let cli = Cli::parse();

    match cli.command {
        Some(Commands::Yell { message }) => yell::run_yell(message),
        None => {
            let mut config = edda_mcp::config::Config::load_from_dir()?;
            if cli.disallow_deployment {
                config.allow_deployment = false;
            }
            run_server(config).await
        }
    }
}

async fn run_server(config: edda_mcp::config::Config) -> Result<()> {
    // detect if running as binary (not via cargo run)
    let is_binary = std::env::var("CARGO").is_err();

    // generate session ID for binary mode (used for both logs and trajectory tracking)
    let session_id = match is_binary {
        true => Some(Uuid::new_v4().to_string()),
        false => None,
    };

    // configure tracing: enabled by default for binary builds, opt-in for cargo run
    let log_path = match (&session_id, std::env::var("RUST_LOG").is_ok()) {
        (Some(session_id), _) => {
            // binary mode: write to session file by default
            let session_short = &session_id[..8];

            let log_dir = paths::session_log_dir();
            std::fs::create_dir_all(&log_dir)?;

            let log_path_buf = log_dir.join(format!("session-{}.log", session_short));

            let log_file = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&log_path_buf)?;

            tracing_subscriber::fmt()
                .with_writer(move || log_file.try_clone().unwrap())
                .init();

            Some(log_path_buf.display().to_string())
        }
        (None, true) => {
            // cargo run mode with RUST_LOG: write to stderr (original behavior)
            tracing_subscriber::fmt()
                .with_writer(std::io::stderr)
                .init();

            None
        }
        (None, false) => None,
    };

    // check if docker is available before initializing providers
    let docker_available = check_docker_available().await.is_ok();
    if !docker_available {
        eprintln!(
            "⚠️  Warning: docker not available - you may have issues with sandbox operations\n"
        );
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
    let deployment = if config.allow_deployment {
        DeploymentProvider::new().ok()
    } else {
        None
    };
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
    if config.allow_deployment && io.is_some() {
        providers_list.push("I/O");
    }

    let log_info = match &log_path {
        Some(path) => format!("\n Logs: {}", path),
        None => String::new(),
    };

    eprintln!(
        "🚀 Edda MCP Server v{} - build data apps deployable on Databricks Apps platform \n\
         Configured providers: {}\n\
         Got questions? eng-appbuild@databricks.com{}\n\
         Server running on stdio transport...",
        env!("CARGO_PKG_VERSION"),
        providers_list.join(", "),
        log_info
    );

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

    provider
        .check_availability(&config.required_providers)
        .map_err(|e| eyre::eyre!(e))?;

    // wrap with trajectory tracking in binary mode
    match session_id {
        Some(session_id) => {
            let tracking_provider = TrajectoryTrackingProvider::new(provider, session_id)?;
            let service = tracking_provider.serve(stdio()).await?;
            service.waiting().await?;
        }
        None => {
            let service = provider.serve(stdio()).await?;
            service.waiting().await?;
        }
    }

    Ok(())
}
