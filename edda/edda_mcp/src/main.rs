use clap::{Parser, Subcommand};
use edda_mcp::paths;
use edda_mcp::providers::{
    CombinedProvider, DatabricksCliProvider, DatabricksRestProvider, DeploymentProvider,
    GoogleSheetsProvider, IOProvider, ProviderType, WorkspaceTools,
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
    /// Full config as JSON (mutually exclusive with other flags)
    #[arg(
        long,
        conflicts_with_all = [
            "with_deployment",
            "with_workspace_tools",
            "template",
            "validation_command",
            "validation_docker_image",
            "screenshot_enabled",
            "screenshot_url",
            "screenshot_port",
            "screenshot_wait_time_ms",
        ]
    )]
    json: Option<String>,

    /// Override with_deployment setting
    #[arg(long = "with-deployment")]
    with_deployment: Option<bool>,

    /// Override with_workspace_tools setting
    #[arg(long = "with-workspace-tools")]
    with_workspace_tools: Option<bool>,

    /// Override template (currently only supports 'Trpc', use --json for Custom)
    #[arg(long = "template")]
    template: Option<String>,

    /// Override validation command
    #[arg(long = "validation.command")]
    validation_command: Option<String>,

    /// Override validation docker image
    #[arg(long = "validation.docker_image")]
    validation_docker_image: Option<String>,

    /// Override screenshot enabled setting
    #[arg(long = "screenshot.enabled")]
    screenshot_enabled: Option<bool>,

    /// Override screenshot URL path
    #[arg(long = "screenshot.url")]
    screenshot_url: Option<String>,

    /// Override screenshot port
    #[arg(long = "screenshot.port")]
    screenshot_port: Option<u16>,

    /// Override screenshot wait time in milliseconds
    #[arg(long = "screenshot.wait_time_ms")]
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

/// Build config overrides from CLI flags
fn build_overrides_from_cli(cli: &Cli) -> Result<edda_mcp::config::ConfigOverrides> {
    use edda_mcp::config::{
        ConfigOverrides, IoConfigOverrides, ScreenshotConfigOverrides, TemplateConfig,
        ValidationConfigOverrides,
    };

    // parse template if provided
    let template = if let Some(template_str) = &cli.template {
        match template_str.as_str() {
            "Trpc" => Some(TemplateConfig::Trpc),
            _ => {
                return Err(eyre::eyre!(
                    "Invalid template '{}'. Only 'Trpc' is supported via CLI. Use --json for Custom templates.",
                    template_str
                ));
            }
        }
    } else {
        None
    };

    // build validation overrides if any field is provided
    let validation = if cli.validation_command.is_some() || cli.validation_docker_image.is_some() {
        Some(ValidationConfigOverrides {
            command: cli.validation_command.clone(),
            docker_image: cli.validation_docker_image.clone(),
        })
    } else {
        None
    };

    // build screenshot overrides if any field is provided
    let screenshot = if cli.screenshot_enabled.is_some()
        || cli.screenshot_url.is_some()
        || cli.screenshot_port.is_some()
        || cli.screenshot_wait_time_ms.is_some()
    {
        Some(ScreenshotConfigOverrides {
            enabled: cli.screenshot_enabled,
            url: cli.screenshot_url.clone(),
            port: cli.screenshot_port,
            wait_time_ms: cli.screenshot_wait_time_ms,
        })
    } else {
        None
    };

    // build io_config overrides if any nested field is provided
    let io_config = if template.is_some() || validation.is_some() || screenshot.is_some() {
        Some(IoConfigOverrides {
            template,
            validation,
            screenshot,
        })
    } else {
        None
    };

    Ok(ConfigOverrides {
        with_deployment: cli.with_deployment,
        with_workspace_tools: cli.with_workspace_tools,
        io_config,
    })
}

/// Load config from file and apply CLI overrides
fn load_config_with_overrides(cli: &Cli) -> Result<edda_mcp::config::Config> {
    use edda_mcp::config::ConfigOverride;

    // Mode 1: JSON replacement
    if let Some(json_str) = &cli.json {
        let config: edda_mcp::config::Config = serde_json::from_str(json_str)
            .map_err(|e| eyre::eyre!("Failed to parse --json config: {}", e))?;
        return Ok(config);
    }

    // Mode 2: Load base config + apply overrides
    let base_config = edda_mcp::config::Config::load_from_dir()?;
    let overrides = build_overrides_from_cli(cli)?;
    let mut config = base_config.apply_override(overrides);

    // special handling: remove deployment provider if disabled
    if !config.with_deployment {
        config
            .required_providers
            .retain(|p| !matches!(p, edda_mcp::providers::ProviderType::Deployment));
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

/// helper to check if provider should be enabled based on config
fn should_enable_provider(config: &edda_mcp::config::Config, provider: ProviderType) -> bool {
    config.required_providers.contains(&provider)
}

/// helper to check if DatabricksRest provider should be enabled (checks both DatabricksRest and legacy Databricks)
fn should_enable_databricks_rest(config: &edda_mcp::config::Config) -> bool {
    config.required_providers.contains(&ProviderType::DatabricksRest)
}

/// helper to check if DatabricksCli provider should be enabled
fn should_enable_databricks_cli(config: &edda_mcp::config::Config) -> bool {
    config.required_providers.contains(&ProviderType::DatabricksCli)
}

/// check environment configuration and prerequisites
async fn check_environment(config: &edda_mcp::config::Config) -> Result<()> {
    use edda_mcp::providers::ProviderType;

    println!("🔍 Checking environment configuration...\n");

    let mut all_passed = true;

    // load env vars for validation
    edda_mcp::env::create_env_example()?;
    let env = edda_mcp::env::EnvVars::load()?;

    // check docker
    print!("  Docker availability... ");
    match check_docker_available().await {
        Ok(_) => println!("✓"),
        Err(e) => {
            println!("✗\n    Error: {}", e);
            all_passed = false;
        }
    }

    // check databricks environment variables only if databricks rest or deployment is required
    let databricks_required = config
        .required_providers
        .contains(&ProviderType::DatabricksRest)
        || config
            .required_providers
            .contains(&ProviderType::Deployment);

    if databricks_required {
        print!("  Databricks credentials... ");
        let require_warehouse = config
            .required_providers
            .contains(&ProviderType::Deployment);
        match env.validate_databricks(require_warehouse) {
            Ok(_) => {
                println!("✓");
                // show which env vars were found
                if let Some(host) = env.databricks_host() {
                    println!("    DATABRICKS_HOST: {}", host);
                }
                println!("    DATABRICKS_TOKEN: [set]");
                if require_warehouse {
                    if let Some(warehouse_id) = env.databricks_warehouse_id() {
                        println!("    DATABRICKS_WAREHOUSE_ID: {}", warehouse_id);
                    }
                }
            }
            Err(e) => {
                println!("✗\n    Error: {}", e);
                all_passed = false;
            }
        }

        // check databricks CLI (optional, only if deployment is required)
        if config
            .required_providers
            .contains(&ProviderType::Deployment)
        {
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
    // load environment variables early (before any other initialization)
    // this ensures .env.example is created and env vars are available
    edda_mcp::env::create_env_example()?;
    let _env = edda_mcp::env::EnvVars::load()?;

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
    let databricks = match should_enable_databricks_rest(&config) {
        true => DatabricksRestProvider::new().ok(),
        false => None,
    };

    // enable DatabricksCli provider if explicitly requested in config
    let databricks_cli = match should_enable_databricks_cli(&config) {
        true => DatabricksCliProvider::new().ok(),
        false => None,
    };

    let deployment = match config.with_deployment {
        true => DeploymentProvider::new().ok(),
        false => None,
    };
    let google_sheets = match should_enable_provider(&config, ProviderType::GoogleSheets) {
        true => GoogleSheetsProvider::new().await.ok(),
        false => None,
    };
    let io = IOProvider::new(config.io_config.clone()).ok();

    // create session context (session_id populated earlier)
    let session_ctx = SessionContext::new(session_id.clone());

    let workspace = match config.with_workspace_tools {
        true => WorkspaceTools::new(session_ctx.clone()).ok(),
        false => None,
    };

    // print startup banner to stderr (won't interfere with stdio MCP transport)
    let mut providers_list = Vec::new();
    if databricks.is_some() {
        providers_list.push("Databricks");
    }
    if databricks_cli.is_some() {
        providers_list.push("Databricks CLI");
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
        databricks_cli,
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
