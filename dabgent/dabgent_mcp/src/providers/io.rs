use dabgent_integrations::ToolResultDisplay;
use dabgent_sandbox::dagger::{ConnectOpts, Logger};
use dabgent_sandbox::{DaggerSandbox, Sandbox};
use dabgent_templates::TemplateTRPC;
use eyre::Result;
use rmcp::handler::server::router::tool::ToolRouter;
use rmcp::handler::server::wrapper::Parameters;
use rmcp::model::{
    CallToolResult, Content, Implementation, ProtocolVersion, ServerCapabilities, ServerInfo,
};
use rmcp::{ErrorData, ServerHandler, tool, tool_handler, tool_router};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::io::ErrorKind;
use std::path::{Path, PathBuf};

/// Internal template enum - not exposed via MCP protocol.
/// Only public for testing purposes.
#[doc(hidden)]
pub enum Template {
    Trpc,
}

impl Template {
    fn description(&self) -> &'static str {
        match self {
            Template::Trpc => include_str!("../../templates/trpc_guidelines.md"),
        }
    }

    fn name(&self) -> &'static str {
        match self {
            Template::Trpc => "tRPC TypeScript",
        }
    }
}

#[derive(Clone)]
pub struct IOProvider {
    tool_router: ToolRouter<Self>,
}

#[derive(Debug, Deserialize, Serialize, JsonSchema)]
pub struct InitiateProjectArgs {
    /// Absolute path to the work directory to copy to (e.g., /path/to/project)
    pub work_dir: String,
    /// If true, wipe the work directory before copying
    #[serde(default)]
    pub force_rewrite: bool,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct InitiateProjectResult {
    pub files_copied: usize,
    pub work_dir: String,
    pub template_name: String,
    pub template_description: String,
}

impl ToolResultDisplay for InitiateProjectResult {
    fn display(&self) -> String {
        format!(
            "Successfully copied {} files from {} template to {}\n\nTemplate: {}\n\n{}",
            self.files_copied,
            self.template_name,
            self.work_dir,
            self.template_name,
            self.template_description
        )
    }
}

#[derive(Debug, Deserialize, Serialize, JsonSchema)]
pub struct ValidateProjectArgs {
    /// Absolute path to the work directory to validate (e.g., /path/to/project)
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

    /// Core logic for initiating a project from template.
    /// Internal implementation - only public for testing purposes.
    #[doc(hidden)]
    pub fn initiate_project_impl(
        work_dir: &Path,
        template: Template,
        force_rewrite: bool,
    ) -> Result<InitiateProjectResult> {
        // handle force rewrite
        if force_rewrite {
            match std::fs::remove_dir_all(work_dir) {
                Ok(_) => {}
                Err(err) if err.kind() == ErrorKind::NotFound => {}
                Err(err) => return Err(err.into()),
            }
        }

        // create work directory if it doesn't exist
        std::fs::create_dir_all(work_dir).map_err(|e| {
            eyre::eyre!(
                "failed to create work directory '{}': {}",
                work_dir.display(),
                e
            )
        })?;

        // collect and copy files using git ls-files
        let template_name = template.name().to_string();
        let template_description = template.description().to_string();
        let files = collect_template_files(template, work_dir)?;

        Ok(InitiateProjectResult {
            files_copied: files.len(),
            work_dir: work_dir.display().to_string(),
            template_name,
            template_description,
        })
    }

    #[tool(
        name = "scaffold_data_app",
        description = "Initialize a project by copying template files from the default TypeScript (tRPC + React) template to a work directory. Supports force rewrite to wipe and recreate the directory. It sets up a basic project structure, and should be ALWAYS used as the first step in creating a new data or web app."
    )]
    pub async fn scaffold_data_app(
        &self,
        Parameters(args): Parameters<InitiateProjectArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let work_path = PathBuf::from(&args.work_dir);

        // validate that the path is absolute
        if !work_path.is_absolute() {
            return Err(ErrorData::invalid_params(
                format!(
                    "work_dir must be an absolute path, got: '{}'. Relative paths are not supported",
                    args.work_dir
                ),
                None,
            ));
        }

        let result = Self::initiate_project_impl(&work_path, Template::Trpc, args.force_rewrite)
            .map_err(|e| {
                ErrorData::internal_error(format!("failed to initiate project: {}", e), None)
            })?;

        Ok(CallToolResult::success(vec![Content::text(
            result.display(),
        )]))
    }

    /// Core logic for validating a project
    pub async fn validate_project_impl(work_dir: &Path) -> Result<ValidateProjectResult> {
        // validate work directory exists
        if !work_dir.exists() {
            eyre::bail!("work directory does not exist: {}", work_dir.display());
        }

        if !work_dir.is_dir() {
            eyre::bail!("work path is not a directory: {}", work_dir.display());
        }

        // use channel to pass validation result out of dagger connection callback
        let (tx, rx) = tokio::sync::oneshot::channel();
        let work_dir_str = work_dir.display().to_string();

        // create connection and run validation
        let opts = ConnectOpts::default()
            .with_logger(Logger::Silent)
            .with_execute_timeout(Some(600));

        let connect_result = opts
            .connect(move |client| async move {
                // create base container with node image
                let mut container = client
                    .container()
                    .from("node:20-alpine3.22")
                    .with_exec(vec!["mkdir", "-p", "/app"]);

                // propagate DATABRICKS_* env vars if set
                if let Ok(host) = std::env::var("DATABRICKS_HOST") {
                    container = container.with_env_variable("DATABRICKS_HOST", host);
                }
                if let Ok(token) = std::env::var("DATABRICKS_TOKEN") {
                    container = container.with_env_variable("DATABRICKS_TOKEN", token);
                }

                // copy work directory to container
                let host_dir = client.host().directory(work_dir_str.clone());
                let container = container.with_directory("/app", host_dir);

                let mut sandbox = DaggerSandbox::from_container(container, client);

                // run validation checks
                let validation_result = run_typescript_validation(&mut sandbox, work_dir_str).await;

                let _ = tx.send(validation_result);
                Ok(())
            })
            .await;

        if let Err(e) = connect_result {
            eyre::bail!("failed to connect to dagger: {}", e);
        }

        let validation_result = rx
            .await
            .map_err(|_| eyre::eyre!("validation task was cancelled"))?;

        let result = match validation_result {
            Ok(_) => ValidateProjectResult {
                success: true,
                message: "All validations passed (build + tests)".to_string(),
                details: None,
            },
            Err(details) => ValidateProjectResult {
                success: false,
                message: "Validation failed".to_string(),
                details: Some(details),
            },
        };

        Ok(result)
    }

    #[tool(
        name = "validate_data_app",
        description = "Validate a project by copying files to a sandbox and running TypeScript compilation check and tests. Returns validation result with success status and details."
    )]
    pub async fn validate_data_app(
        &self,
        Parameters(args): Parameters<ValidateProjectArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let work_path = PathBuf::from(&args.work_dir);

        // validate that the path is absolute
        if !work_path.is_absolute() {
            return Err(ErrorData::invalid_params(
                format!(
                    "work_dir must be an absolute path, got: '{}'. Relative paths are not supported",
                    args.work_dir
                ),
                None,
            ));
        }

        let result = Self::validate_project_impl(&work_path).await.map_err(|e| {
            ErrorData::internal_error(format!("failed to validate project: {}", e), None)
        })?;

        Ok(CallToolResult::success(vec![Content::text(
            result.display(),
        )]))
    }
}

async fn run_typescript_validation(
    sandbox: &mut DaggerSandbox,
    work_dir: String,
) -> Result<(), ValidationDetails> {
    tracing::info!("Starting validation (build + tests)...");

    refresh_sandbox_files(sandbox, &work_dir).await?;
    run_build(sandbox).await?;
    run_tests(sandbox).await?;

    tracing::info!("All validation checks passed");
    Ok(())
}

async fn refresh_sandbox_files(
    sandbox: &mut DaggerSandbox,
    work_dir: &str,
) -> Result<(), ValidationDetails> {
    sandbox
        .refresh_from_host(work_dir, "/app")
        .await
        .map_err(|e| ValidationDetails {
            exit_code: -1,
            stdout: String::new(),
            stderr: format!("Failed to refresh from host: {}", e),
        })
}

async fn run_build(sandbox: &mut DaggerSandbox) -> Result<(), ValidationDetails> {
    let build_result = sandbox
        .exec("cd /app && npm run build")
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

    tracing::info!("Build passed");
    Ok(())
}

async fn run_tests(sandbox: &mut DaggerSandbox) -> Result<(), ValidationDetails> {
    let test_result = sandbox
        .exec("cd /app && npm test")
        .await
        .map_err(|e| ValidationDetails {
            exit_code: -1,
            stdout: String::new(),
            stderr: format!("Failed to run npm test: {}", e),
        })?;

    if test_result.exit_code != 0 {
        tracing::error!("npm test failed: {:?}", test_result);
        return Err(ValidationDetails {
            exit_code: test_result.exit_code,
            stdout: test_result.stdout,
            stderr: test_result.stderr,
        });
    }

    tracing::info!("Tests passed");
    Ok(())
}

fn extract_files(template: Template) -> Vec<(String, String)> {
    let mut files = Vec::new();
    match template {
        Template::Trpc => {
            for path in TemplateTRPC::iter() {
                if let Some(file) = TemplateTRPC::get(path.as_ref()) {
                    files.push((
                        path.to_string(),
                        String::from_utf8_lossy(&file.data).into_owned(),
                    ));
                }
            }
        }
    }
    files.sort_by(|a, b| a.0.cmp(&b.0));
    files
}

fn collect_template_files(template: Template, work_path: &Path) -> Result<Vec<PathBuf>> {
    let template_files = extract_files(template);
    let mut copied_files = Vec::new();
    for (template_path, contents) in template_files.iter() {
        if template_path.is_empty() {
            continue;
        }

        let target_file = work_path.join(template_path);

        // ensure parent directory exists
        if let Some(parent) = target_file.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                eyre::eyre!(
                    "failed to create directory '{}' for file '{}': {}",
                    parent.display(),
                    target_file.display(),
                    e
                )
            })?;
        }

        // write file
        std::fs::write(&target_file, contents)
            .map_err(|e| eyre::eyre!("failed to write file '{}': {}", target_file.display(), e))?;

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
