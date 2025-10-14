use dabgent_integrations::ToolResultDisplay;
use dabgent_sandbox::dagger::{ConnectOpts, Logger};
use dabgent_sandbox::{DaggerSandbox, Sandbox};
use eyre::Result;
use rmcp::handler::server::router::tool::ToolRouter;
use rmcp::handler::server::wrapper::Parameters;
use rmcp::model::{
    CallToolResult, Content, Implementation, ProtocolVersion, ServerCapabilities, ServerInfo,
};
use rmcp::{tool, tool_handler, tool_router, ErrorData, ServerHandler};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

pub const DEFAULT_TEMPLATE_PATH: &str = "../../dataapps/template_trpc";

#[derive(Clone)]
pub struct IOProvider {
    tool_router: ToolRouter<Self>,
}

#[derive(Debug, Deserialize, Serialize, JsonSchema)]
pub struct InitiateProjectArgs {
    /// Path to the work directory to copy to
    pub work_dir: String,
    /// If true, wipe the work directory before copying
    #[serde(default)]
    pub force_rewrite: bool,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct InitiateProjectResult {
    pub files_copied: usize,
    pub work_dir: String,
    pub template_source: String,
}

impl ToolResultDisplay for InitiateProjectResult {
    fn display(&self) -> String {
        format!(
            "Successfully copied {} files from default template to {}",
            self.files_copied, self.work_dir
        )
    }
}

#[derive(Debug, Deserialize, Serialize, JsonSchema)]
pub struct ValidateProjectArgs {
    /// Path to the work directory to validate
    pub work_dir: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ValidateProjectResult {
    pub success: bool,
    pub message: String,
    pub details: Option<ValidationDetails>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ValidationDetails {
    pub exit_code: isize,
    pub stdout: String,
    pub stderr: String,
}

impl ToolResultDisplay for ValidateProjectResult {
    fn display(&self) -> String {
        if self.success {
            format!("Validation passed: {}", self.message)
        } else {
            match &self.details {
                Some(details) => format!(
                    "Validation failed: {}\nExit code: {}\nStdout: {}\nStderr: {}",
                    self.message, details.exit_code, details.stdout, details.stderr
                ),
                None => format!("Validation failed: {}", self.message),
            }
        }
    }
}


#[tool_router]
impl IOProvider {
    pub fn new() -> Result<Self> {
        Ok(Self {
            tool_router: Self::tool_router(),
        })
    }

    #[tool(
        name = "initiate_project",
        description = "Initialize a project by copying template files from the default TypeScript (tRPC + React) template to a work directory. Supports force rewrite to wipe and recreate the directory."
    )]
    pub async fn initiate_project(
        &self,
        Parameters(args): Parameters<InitiateProjectArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        // use hardcoded template path
        let manifest_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
        let template_path = manifest_dir.join(DEFAULT_TEMPLATE_PATH);
        let work_path = PathBuf::from(&args.work_dir);

        // validate template directory exists
        if !template_path.exists() {
            return Err(ErrorData::internal_error(
                format!("default template directory does not exist: {}", template_path.display()),
                None,
            ));
        }

        if !template_path.is_dir() {
            return Err(ErrorData::internal_error(
                format!("default template path is not a directory: {}", template_path.display()),
                None,
            ));
        }

        // handle force rewrite
        if args.force_rewrite && work_path.exists() {
            std::fs::remove_dir_all(&work_path).map_err(|e| {
                ErrorData::internal_error(
                    format!("failed to remove work directory: {}", e),
                    None,
                )
            })?;
        }

        // create work directory if it doesn't exist
        std::fs::create_dir_all(&work_path).map_err(|e| {
            ErrorData::internal_error(format!("failed to create work directory: {}", e), None)
        })?;

        // collect and copy files using git ls-files
        let files = collect_template_files(&template_path, &work_path).map_err(|e| {
            ErrorData::internal_error(format!("failed to collect template files: {}", e), None)
        })?;

        let result = InitiateProjectResult {
            files_copied: files.len(),
            work_dir: args.work_dir,
            template_source: "default template".to_string(),
        };

        Ok(CallToolResult::success(vec![Content::text(result.display())]))
    }

    #[tool(
        name = "validate_project",
        description = "Validate a project by copying files to a sandbox and running TypeScript compilation check. Returns validation result with success status and details."
    )]
    pub async fn validate_project(
        &self,
        Parameters(args): Parameters<ValidateProjectArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let work_path = PathBuf::from(&args.work_dir);

        // validate work directory exists
        if !work_path.exists() {
            return Err(ErrorData::invalid_params(
                format!("work directory does not exist: {}", work_path.display()),
                None,
            ));
        }

        if !work_path.is_dir() {
            return Err(ErrorData::invalid_params(
                format!("work path is not a directory: {}", work_path.display()),
                None,
            ));
        }

        // use channel to pass validation result out of dagger connection callback
        let (tx, rx) = tokio::sync::oneshot::channel();
        let work_dir = args.work_dir.clone();

        // create connection and run validation
        let opts = ConnectOpts::default()
            .with_logger(Logger::Silent)
            .with_execute_timeout(Some(600));

        let connect_result = opts
            .connect(move |client| async move {
                // create base container with node image
                let container = client
                    .container()
                    .from("node:20-alpine")
                    .with_exec(vec!["mkdir", "-p", "/app"]);

                // copy work directory to container
                let host_dir = client.host().directory(work_dir);
                let container = container.with_directory("/app", host_dir);

                let mut sandbox = DaggerSandbox::from_container(container, client);

                // run validation checks
                let validation_result = run_typescript_validation(&mut sandbox).await;

                let _ = tx.send(validation_result);
                Ok(())
            })
            .await;

        if let Err(e) = connect_result {
            return Err(ErrorData::internal_error(
                format!("failed to connect to dagger: {}", e),
                None,
            ));
        }

        let validation_result = rx.await.map_err(|_| {
            ErrorData::internal_error("validation task was cancelled".to_string(), None)
        })?;

        let result = match validation_result {
            Ok(_) => ValidateProjectResult {
                success: true,
                message: "TypeScript compilation passed".to_string(),
                details: None,
            },
            Err(details) => ValidateProjectResult {
                success: false,
                message: "TypeScript compilation failed".to_string(),
                details: Some(details),
            },
        };

        Ok(CallToolResult::success(vec![Content::text(result.display())]))
    }
}

async fn run_typescript_validation(
    sandbox: &mut DaggerSandbox,
) -> Result<(), ValidationDetails> {
    tracing::info!("Starting TypeScript validation...");

    // determine the correct directory - check if client/ exists (for template_trpc)
    // otherwise assume we're at the root
    let check_client = sandbox
        .exec("test -f /app/client/package.json && echo 'client' || echo 'root'")
        .await
        .map_err(|e| ValidationDetails {
            exit_code: -1,
            stdout: String::new(),
            stderr: format!("Failed to check directory structure: {}", e),
        })?;

    let npm_dir = if check_client.stdout.trim() == "client" {
        "/app/client"
    } else {
        "/app"
    };

    tracing::info!("Using npm directory: {}", npm_dir);

    // install dependencies
    let install_result = sandbox
        .exec(&format!("cd {} && npm install", npm_dir))
        .await
        .map_err(|e| ValidationDetails {
            exit_code: -1,
            stdout: String::new(),
            stderr: format!("Failed to run npm install: {}", e),
        })?;

    if install_result.exit_code != 0 {
        tracing::error!("npm install failed: {:?}", install_result);
        return Err(ValidationDetails {
            exit_code: install_result.exit_code,
            stdout: install_result.stdout,
            stderr: install_result.stderr,
        });
    }

    // run typescript compilation
    let build_result = sandbox
        .exec(&format!("cd {} && npm run build", npm_dir))
        .await
        .map_err(|e| ValidationDetails {
            exit_code: -1,
            stdout: String::new(),
            stderr: format!("Failed to run npm build: {}", e),
        })?;

    if build_result.exit_code != 0 {
        tracing::error!("npm build failed: {:?}", build_result);
        return Err(ValidationDetails {
            exit_code: build_result.exit_code,
            stdout: build_result.stdout,
            stderr: build_result.stderr,
        });
    }

    tracing::info!("TypeScript validation passed");
    Ok(())
}

fn collect_template_files(template_path: &Path, work_path: &Path) -> Result<Vec<PathBuf>> {
    use std::process::Command;

    let output = Command::new("git")
        .arg("-C")
        .arg(template_path)
        .arg("ls-files")
        .output()?;

    if !output.status.success() {
        eyre::bail!("git ls-files failed");
    }

    let files_list = String::from_utf8(output.stdout)?;
    let mut copied_files = Vec::new();

    for relative_path in files_list.lines() {
        if relative_path.is_empty() {
            continue;
        }

        let source_file = template_path.join(relative_path);
        let target_file = work_path.join(relative_path);

        // ensure parent directory exists
        if let Some(parent) = target_file.parent() {
            std::fs::create_dir_all(parent)?;
        }

        // copy file
        std::fs::copy(&source_file, &target_file)?;
        copied_files.push(target_file);
    }

    Ok(copied_files)
}

#[tool_handler]
impl ServerHandler for IOProvider {
    fn get_info(&self) -> ServerInfo {
        ServerInfo {
            protocol_version: ProtocolVersion::V_2024_11_05,
            capabilities: ServerCapabilities::builder().enable_tools().build(),
            server_info: Implementation {
                name: "dabgent-mcp-io".to_string(),
                version: env!("CARGO_PKG_VERSION").to_string(),
                title: Some("Dabgent MCP - I/O".to_string()),
                website_url: None,
                icons: None,
            },
            instructions: Some(
                "MCP server providing I/O tools for project initialization, template management, and validation.".to_string(),
            ),
        }
    }
}
