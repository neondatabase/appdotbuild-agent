use clap::{Parser, Subcommand};
use edda_mcp::paths;
use edda_mcp::providers::{
    CombinedProvider, DatabricksProvider, DeploymentProvider, GoogleSheetsProvider, IOProvider,
    WorkspaceTools,
};
use edda_mcp::session::SessionContext;
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
    /// Override allow_deployment setting
    #[arg(long = "with-deployment")]
    with_deployment: Option<bool>,

    /// Override with_workspace_tools setting
    #[arg(long = "with-workspace-tools")]
    with_workspace_tools: Option<bool>,

    /// Override I/O config with JSON (e.g., '{"template":"Trpc"}' or '{"template":{"Custom":{"path":"/path"}}}')
    #[arg(long)]
    io_config: Option<String>,

    /// Override screenshot enabled setting
    #[arg(long = "io.screenshot.enabled")]
    screenshot_enabled: Option<bool>,

    /// Override screenshot URL path
    #[arg(long = "io.screenshot.url")]
    screenshot_url: Option<String>,

    /// Override screenshot port
    #[arg(long = "io.screenshot.port")]
    screenshot_port: Option<u16>,

    /// Override screenshot wait time in milliseconds
    #[arg(long = "io.screenshot.wait_time_ms")]
    screenshot_wait_time_ms: Option<u64>,

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
    /// Check environment configuration and prerequisites
    Check,
}

/// load config from file and apply CLI overrides
fn load_config_with_overrides(cli: &Cli) -> Result<edda_mcp::config::Config> {
    use edda_mcp::config::{ConfigOverrides, ScreenshotOverrides};

    let mut config = edda_mcp::config::Config::load_from_dir()?;

    // handle legacy JSON override (kept for backward compatibility)
    if let Some(io_config_json) = &cli.io_config {
        let io_config: edda_mcp::config::IoConfig =
            serde_json::from_str(io_config_json)
                .map_err(|e| eyre::eyre!("Failed to parse --io_config JSON: {}", e))?;
        config.io_config = Some(io_config);
    }

    // build screenshot overrides if any flag is provided
    let screenshot_overrides = if cli.screenshot_enabled.is_some()
        || cli.screenshot_url.is_some()
        || cli.screenshot_port.is_some()
        || cli.screenshot_wait_time_ms.is_some()
    {
        Some(ScreenshotOverrides {
            enabled: cli.screenshot_enabled,
            url: cli.screenshot_url.clone(),
            port: cli.screenshot_port,
            wait_time_ms: cli.screenshot_wait_time_ms,
        })
    } else {
        None
    };

    // build config overrides struct
    let overrides = ConfigOverrides {
        with_deployment: cli.with_deployment,
        with_workspace_tools: cli.with_workspace_tools,
        screenshot: screenshot_overrides,
    };

    // apply all overrides in single place
    let mut config = config.apply_overrides(overrides);

    // special handling: remove deployment provider if disabled
    if config.with_deployment == false {
        config.required_providers.retain(|p| !matches!(p, edda_mcp::providers::ProviderType::Deployment));
    }

    Ok(config)
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

/// check environment configuration and prerequisites
async fn check_environment(config: &edda_mcp::config::Config) -> Result<()> {
    use edda_mcp::providers::ProviderType;

    println!("🔍 Checking environment configuration...\n");

    let mut all_passed = true;

    // check docker
    print!("  Docker availability... ");
    match check_docker_available().await {
        Ok(_) => println!("✓"),
        Err(e) => {
            println!("✗\n    Error: {}", e);
            all_passed = false;
        }
    }

    // check databricks environment variables only if databricks or deployment is required
    let databricks_required = config.required_providers.contains(&ProviderType::Databricks)
        || config.required_providers.contains(&ProviderType::Deployment);

    if databricks_required {
        let databricks_checks = [
            ("DATABRICKS_HOST", true),
            ("DATABRICKS_TOKEN", true),
            ("DATABRICKS_WAREHOUSE_ID", config.required_providers.contains(&ProviderType::Deployment)),
        ];

        for (var_name, required) in databricks_checks {
            print!("  {}... ", var_name);
            match std::env::var(var_name) {
                Ok(value) if !value.is_empty() => {
                    println!("✓");
                    // warn if DATABRICKS_HOST starts with http
                    if var_name == "DATABRICKS_HOST" && value.starts_with("http") {
                        println!("    ⚠ Warning: DATABRICKS_HOST should not include protocol");
                        println!("    Some clients may struggle with this format");
                    }
                }
                _ => {
                    if required {
                        println!("✗\n    Error: {} environment variable not set", var_name);
                        all_passed = false;
                    } else {
                        println!("⚠ (optional for your config)");
                    }
                }
            }
        }

        // check databricks CLI (optional, only if deployment is required)
        if config.required_providers.contains(&ProviderType::Deployment) {
            print!("  Databricks CLI... ");
            match tokio::process::Command::new("databricks")
                .arg("--version")
                .output()
                .await
            {
                Ok(output) if output.status.success() => println!("✓"),
                _ => println!("⚠ (optional, needed for deployment)"),
            }
        }
    }

    // sandbox warmup (only if docker is available)
    if check_docker_available().await.is_ok() {
        println!("\n  Sandbox warmup started. It may take a while on first run...");
        match warmup_sandbox().await {
            Ok(_) => println!("  Sandbox warmup complete ✓"),
            Err(e) => {
                println!("  Sandbox warmup failed ✗\n    Error: {}", e);
                all_passed = false;
            }
        }
    }

    println!();

    if all_passed {
        println!("✅ All checks passed!");
        Ok(())
    } else {
        println!("❌ Some checks failed. Please review the errors above.");
        Err(eyre::eyre!("Environment check failed"))
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();

    match cli.command {
        Some(Commands::Yell { message }) => yell::run_yell(message),
        Some(Commands::Check) => {
            let config = load_config_with_overrides(&cli)?;
            check_environment(&config).await
        }
        None => {
            let config = load_config_with_overrides(&cli)?;
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
                .with_ansi(false)
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

    // spawn non-blocking version check
    tokio::spawn(async {
        if let Err(e) = edda_mcp::version_check::check_for_updates().await {
            tracing::debug!("Version check failed: {}", e);
        }
    });

    // initialize all available providers
    let databricks = DatabricksProvider::new().ok();
    let deployment = if config.with_deployment {
        DeploymentProvider::new().ok()
    } else {
        None
    };
    let google_sheets = GoogleSheetsProvider::new().await.ok();
    let io = IOProvider::new(config.io_config.clone()).ok();

    // create session context (session_id populated earlier)
    let session_ctx = SessionContext::new(session_id.clone());

    let workspace = if config.with_workspace_tools {
        WorkspaceTools::new(session_ctx.clone()).ok()
    } else {
        None
    };

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
    if config.with_deployment && io.is_some() {
        providers_list.push("I/O");
    }
    if workspace.is_some() {
        providers_list.push("Workspace");
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
    let provider = CombinedProvider::new(
        session_ctx,
        databricks,
        deployment,
        google_sheets,
        io,
        workspace,
        &config,
    )
    .map_err(|_| {
        eyre::eyre!(
            "No integrations available. Configure at least one:\n\
             - Databricks: Set DATABRICKS_HOST and DATABRICKS_TOKEN\n\
             - Deployment: Set DATABRICKS_HOST and DATABRICKS_TOKEN)\n\
             - Google Sheets: Place credentials at ~/.config/gspread/credentials.json\n\
             - I/O: Always available (includes Workspace tools)"
        )
    })?;

    provider
        .check_availability(&config.required_providers)
        .map_err(|e| eyre::eyre!(e))?;

    // wrap with trajectory tracking in binary mode
    match session_id {
        Some(session_id) => {
            let tracking_provider = TrajectoryTrackingProvider::new(provider, session_id, config)?;
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
