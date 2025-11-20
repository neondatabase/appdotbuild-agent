use crate::config::TemplateConfig;
use crate::state;
use edda_integrations::ToolResultDisplay;
use edda_sandbox::dagger::{ConnectOpts, Logger};
use edda_sandbox::{DaggerConn, DaggerSandbox, Sandbox};
use edda_templates::{LocalTemplate, Template, TemplateCore, TemplateTRPC};
use eyre::{Context, Result};
use rmcp::handler::server::router::tool::ToolRouter;
use rmcp::handler::server::wrapper::Parameters;
use rmcp::model::{CallToolResult, Content, ServerInfo};
use rmcp::{ErrorData, ServerHandler, tool, tool_handler, tool_router};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::io::ErrorKind;
use std::path::{Path, PathBuf};


#[derive(Clone)]
pub struct IOProvider {
    tool_router: ToolRouter<Self>,
    config: Option<crate::config::IoConfig>,
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
    pub file_tree: String,
}

impl ToolResultDisplay for InitiateProjectResult {
    fn display(&self) -> String {
        format!(
            "Successfully copied {} files from {} template to {}\n\nTemplate: {}\n\n{}\n\nFile structure:\n{}",
            self.files_copied,
            self.template_name,
            self.work_dir,
            self.template_name,
            self.template_description,
            self.file_tree
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
    pub screenshot_path: Option<String>,
    pub browser_logs: Option<String>,
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
            let mut msg = format!("Validation passed: {}", self.message);
            if let Some(screenshot) = &self.screenshot_path {
                msg.push_str(&format!("\n\nScreenshot: {}, review it to make sure the app is visually fine.", screenshot));
            }
            if let Some(logs) = &self.browser_logs {
                msg.push_str(&format!("\n\nBrowser console logs:\n{}", logs));
            }
            msg
        } else {
            let mut msg = format!("Validation failed: {}", self.message);
            if let Some(details) = &self.details {
                msg.push_str(&format!(
                    "\nExit code: {}\nStdout: {}\nStderr: {}",
                    details.exit_code, details.stdout, details.stderr
                ));
            }
            if let Some(logs) = &self.browser_logs {
                msg.push_str(&format!("\n\nBrowser console logs:\n{}", logs));
            }
            msg
        }
    }
}

#[tool_router]
impl IOProvider {
    pub fn new(config: Option<crate::config::IoConfig>) -> Result<Self> {
        Ok(Self {
            tool_router: Self::tool_router(),
            config,
        })
    }

    /// Get the template to use based on the config
    fn get_template(&self) -> TemplateFiles {
        match self.config {
            Some(ref cfg) => match &cfg.template {
                TemplateConfig::Trpc => TemplateFiles::Trpc(TemplateTRPC),
                TemplateConfig::Custom { name, path } => {
                    let path = std::path::PathBuf::from(path);
                    let template = LocalTemplate::from_dir(&name, &path).unwrap();
                    TemplateFiles::Local(template)
                }
            },
            None => TemplateFiles::Trpc(TemplateTRPC),
        }
    }

    fn get_validation_strategy(&self) -> Box<dyn validation::ValidationDyn> {
        use validation::Validation;
        if let Some(cfg) = &self.config {
            if let Some(val_config) = &cfg.validation {
                return validation::ValidationCmd {
                    command: val_config.command.clone(),
                    docker_image: val_config.docker_image.clone(),
                }
                .boxed();
            }
        }
        validation::ValidationTRPC.boxed()
    }

    /// Core logic for initiating a project from template.
    /// Internal implementation - only public for testing purposes.
    #[doc(hidden)]
    pub fn initiate_project_impl(
        work_dir: &Path,
        template: impl Template,
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

        let template_name = template.name().to_string();
        let template_description = template.description().unwrap_or("".to_string());
        let files = template.extract(work_dir)?;

        // generate file tree
        let file_tree = Self::generate_file_tree(work_dir, &files)?;

        Ok(InitiateProjectResult {
            files_copied: files.len(),
            work_dir: work_dir.display().to_string(),
            template_name,
            template_description,
            file_tree,
        })
    }

    /// Generate a tree-style visualization of the file structure
    /// Collapses directories with more than 10 files to avoid clutter
    fn generate_file_tree(_base_dir: &Path, files: &[PathBuf]) -> Result<String> {
        use std::collections::BTreeMap;

        const MAX_FILES_TO_SHOW: usize = 10;

        // build a tree structure
        let mut tree: BTreeMap<String, Vec<String>> = BTreeMap::new();

        for file in files {
            let path_str = file.to_string_lossy().to_string();
            let parts: Vec<&str> = path_str.split('/').collect();

            if parts.len() == 1 {
                // root level file
                tree.entry("".to_string())
                    .or_insert_with(Vec::new)
                    .push(parts[0].to_string());
            } else {
                // file in subdirectory
                let dir = parts[..parts.len() - 1].join("/");
                let file_name = parts[parts.len() - 1].to_string();
                tree.entry(dir)
                    .or_insert_with(Vec::new)
                    .push(file_name);
            }
        }

        // format as tree
        let mut output = String::new();
        let mut sorted_dirs: Vec<_> = tree.keys().collect();
        sorted_dirs.sort();

        for dir in sorted_dirs {
            let files_in_dir = &tree[dir];
            if dir.is_empty() {
                // root files - always show all
                for file in files_in_dir {
                    output.push_str(&format!("{}\n", file));
                }
            } else {
                // directory
                output.push_str(&format!("{}/\n", dir));
                if files_in_dir.len() <= MAX_FILES_TO_SHOW {
                    // show all files
                    for file in files_in_dir {
                        output.push_str(&format!("  {}\n", file));
                    }
                } else {
                    // collapse large directories
                    output.push_str(&format!("  ({} files)\n", files_in_dir.len()));
                }
            }
        }

        Ok(output)
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

        let template = self.get_template();
        let result = Self::initiate_project_impl(&work_path, template, args.force_rewrite)
            .map_err(|e| {
                ErrorData::internal_error(format!("failed to initiate project: {}", e), None)
            })?;

        Ok(CallToolResult::success(vec![Content::text(
            result.display(),
        )]))
    }

    /// Capture screenshot of the app using edda_screenshot
    /// Returns (screenshot_path, browser_logs) on success, or error with logs attached
    async fn capture_screenshot(
        client: &DaggerConn,
        work_dir: &Path,
        screenshot_config: Option<&crate::config::ScreenshotConfig>,
    ) -> Result<(String, Option<String>)> {
        // check if Dockerfile exists
        let dockerfile_path = work_dir.join("Dockerfile");
        if !dockerfile_path.exists() {
            eyre::bail!(
                "Dockerfile required for screenshot validation. Expected at: {}",
                dockerfile_path.display()
            );
        }

        // build ScreenshotOptions from config, using defaults for None fields
        let defaults = edda_screenshot::ScreenshotOptions::default();
        let default_cfg = crate::config::ScreenshotConfig::default();
        let screenshot_cfg = screenshot_config.unwrap_or(&default_cfg);

        let options = edda_screenshot::ScreenshotOptions {
            url: screenshot_cfg.url.clone().unwrap_or(defaults.url),
            port: screenshot_cfg.port.unwrap_or(defaults.port),
            wait_time_ms: screenshot_cfg.wait_time_ms.unwrap_or(defaults.wait_time_ms),
            env_vars: {
                let mut vars = vec![];
                if let Ok(host) = std::env::var("DATABRICKS_HOST") {
                    vars.push(("DATABRICKS_HOST".to_string(), host));
                }
                if let Ok(token) = std::env::var("DATABRICKS_TOKEN") {
                    vars.push(("DATABRICKS_TOKEN".to_string(), token));
                }
                if let Ok(warehouse_id) = std::env::var("DATABRICKS_WAREHOUSE_ID") {
                    vars.push(("DATABRICKS_WAREHOUSE_ID".to_string(), warehouse_id));
                }
                vars
            },
        };

        tracing::info!("Starting screenshot capture with options: url={}, port={}, wait_time={}ms",
            options.url, options.port, options.wait_time_ms);

        // get app source directory
        let app_source = client.host().directory(work_dir.display().to_string());

        // capture screenshot and handle errors with context
        let result_dir = edda_screenshot::screenshot_app(client, app_source, options)
            .await
            .context("Screenshot capture failed (app may not have started)")?;

        // export screenshot to work_dir/screenshot.png
        let screenshot_path = work_dir.join("screenshot.png");
        result_dir
            .file("screenshot.png")
            .export(screenshot_path.display().to_string())
            .await
            .context("failed to export screenshot")?;

        tracing::info!("Screenshot saved to: {}", screenshot_path.display());

        // read browser console logs if available (soft failure - empty string if missing)
        let browser_logs = match result_dir.file("logs.txt").contents().await {
            Ok(logs) => {
                if !logs.trim().is_empty() {
                    tracing::info!("Browser console logs captured ({} bytes)", logs.len());
                    Some(logs)
                } else {
                    tracing::debug!("Browser logs file is empty");
                    None
                }
            }
            Err(e) => {
                tracing::warn!("Failed to read browser logs (screenshot succeeded, logs missing): {}", e);
                None
            }
        };

        // return absolute path for agent to read
        Ok((screenshot_path.display().to_string(), browser_logs))
    }

    /// Core logic for validating a project
    pub async fn validate_project_impl(
        work_dir: &Path,
        validation_strategy: Box<dyn validation::ValidationDyn>,
        screenshot_config: Option<crate::config::ScreenshotConfig>,
    ) -> Result<ValidateProjectResult> {
        // validate work directory exists
        if !work_dir.exists() {
            eyre::bail!("work directory does not exist: {}", work_dir.display());
        }

        if !work_dir.is_dir() {
            eyre::bail!("work path is not a directory: {}", work_dir.display());
        }

        // load project state
        let project_state = match state::load_state(work_dir)? {
            Some(state) => state,
            None => {
                tracing::warn!("Project not scaffolded by edda, but proceeding with validation");
                state::ProjectState::new()
            }
        };

        // optimization: spawn screenshot task early if enabled
        // this allows parallel execution: validation checks + screenshot warmup/capture
        let screenshot_task = if screenshot_config
            .as_ref()
            .map_or(false, |c| c.enabled.unwrap_or(true))
        {
            let work_dir_clone = work_dir.to_path_buf();
            let screenshot_config_clone = screenshot_config.clone();

            tracing::info!("Spawning screenshot task in parallel with validation");

            Some(tokio::spawn(async move {
                let (screenshot_tx, screenshot_rx) = tokio::sync::oneshot::channel();

                let screenshot_opts = ConnectOpts::default()
                    .with_logger(Logger::Silent)
                    .with_execute_timeout(Some(600));

                let screenshot_connect_result = screenshot_opts
                    .connect(move |client| async move {
                        let result = IOProvider::capture_screenshot(
                            &client,
                            &work_dir_clone,
                            screenshot_config_clone.as_ref(),
                        )
                        .await;
                        let _ = screenshot_tx.send(result);
                        Ok(())
                    })
                    .await;

                if let Err(e) = screenshot_connect_result {
                    return Err(eyre::eyre!("failed to connect to dagger for screenshot: {}", e));
                }

                screenshot_rx
                    .await
                    .map_err(|_| eyre::eyre!("screenshot task was cancelled"))?
            }))
        } else {
            None
        };

        // run validation checks in main thread
        let (tx, rx) = tokio::sync::oneshot::channel();
        let work_dir_str = work_dir.display().to_string();
        let docker_image = validation_strategy.docker_image();

        let opts = ConnectOpts::default()
            .with_logger(Logger::Silent)
            .with_execute_timeout(Some(600));

        let connect_result = opts
            .connect(move |client| async move {
                // create base container with configured image
                let mut container = client
                    .container()
                    .from(&docker_image)
                    .with_exec(vec!["mkdir", "-p", "/app"]);

                // propagate DATABRICKS_* env vars if set
                if let Ok(host) = std::env::var("DATABRICKS_HOST") {
                    container = container.with_env_variable("DATABRICKS_HOST", host);
                }
                if let Ok(token) = std::env::var("DATABRICKS_TOKEN") {
                    container = container.with_env_variable("DATABRICKS_TOKEN", token);
                }
                if let Ok(warehouse_id) = std::env::var("DATABRICKS_WAREHOUSE_ID") {
                    container =
                        container.with_env_variable("DATABRICKS_WAREHOUSE_ID", warehouse_id);
                }

                // copy work directory to container
                let host_dir = client.host().directory(work_dir_str.clone());
                let container = container.with_directory("/app", host_dir);

                let mut sandbox = DaggerSandbox::from_container(container, client);

                // run validation checks using the strategy
                let validation_result = validation_strategy
                    .validate(&mut sandbox, &work_dir_str)
                    .await;

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
            Ok(_) => {
                // validation passed - update state and await screenshot if spawned
                let checksum = state::compute_checksum(work_dir)?;
                let project_state = project_state.validate(checksum)?;
                state::save_state(work_dir, &project_state)?;

                // await screenshot task with timeout if it was spawned
                let (screenshot_path, browser_logs) = if let Some(task) = screenshot_task {
                    tracing::info!("Validation passed, awaiting screenshot result");

                    use tokio::time::{timeout, Duration};
                    let screenshot_timeout = Duration::from_secs(300); // 5 minutes

                    match timeout(screenshot_timeout, task).await {
                        Ok(Ok(Ok((path, logs)))) => (Some(path), logs),
                        Ok(Ok(Err(e))) => {
                            // Screenshot failed, but validation passed - soft failure
                            tracing::warn!("Screenshot capture failed (validation passed): {}", e);
                            let error_msg = format!("Screenshot failed: {}", e);
                            (None, Some(error_msg))
                        }
                        Ok(Err(e)) => {
                            tracing::warn!("Screenshot task panicked (validation passed): {}", e);
                            let error_msg = format!("Screenshot task panicked: {}", e);
                            (None, Some(error_msg))
                        }
                        Err(_) => {
                            tracing::warn!("Screenshot timed out after {} seconds (validation passed)", screenshot_timeout.as_secs());
                            (None, Some("Screenshot timed out".to_string()))
                        }
                    }
                } else {
                    (None, None)
                };

                ValidateProjectResult {
                    success: true,
                    message: "All validations passed".to_string(),
                    details: None,
                    screenshot_path,
                    browser_logs,
                }
            }
            Err(details) => {
                // validation failed - explicitly abort screenshot task
                if let Some(task) = screenshot_task {
                    tracing::info!("Validation failed, aborting screenshot task");
                    task.abort();
                    let _ = task.await; // Wait for abort to complete, ignore result
                }

                ValidateProjectResult {
                    success: false,
                    message: "Validation failed".to_string(),
                    details: Some(details),
                    screenshot_path: None,
                    browser_logs: None,
                }
            }
        };

        Ok(result)
    }

    #[tool(
        name = "validate_data_app",
        description = "Validate a project by copying files to a sandbox and running validation checks. Project should be scaffolded first. Returns validation result with success status and details."
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

        let validation_strategy = self.get_validation_strategy();
        let screenshot_config = self.config.as_ref().and_then(|c| c.screenshot.clone());
        let result = Self::validate_project_impl(
            &work_path,
            validation_strategy,
            screenshot_config,
        )
        .await
        .map_err(|e| {
            ErrorData::internal_error(format!("failed to validate project: {}", e), None)
        })?;

        match result.success {
            true => Ok(CallToolResult::success(vec![Content::text(
                result.display(),
            )])),
            false => Ok(CallToolResult::error(vec![Content::text(result.display())])),
        }
    }
}

enum TemplateFiles {
    Trpc(TemplateTRPC),
    Local(LocalTemplate),
}

impl Template for TemplateFiles {
    fn name(&self) -> String {
        match self {
            TemplateFiles::Trpc(t) => t.name(),
            TemplateFiles::Local(t) => t.name(),
        }
    }
}

impl TemplateCore for TemplateFiles {
    fn description(&self) -> Option<String> {
        match self {
            TemplateFiles::Trpc(t) => t.description(),
            TemplateFiles::Local(t) => t.description(),
        }
    }

    fn extract(&self, work_dir: &Path) -> Result<Vec<PathBuf>> {
        match self {
            TemplateFiles::Trpc(t) => t.extract(work_dir),
            TemplateFiles::Local(t) => t.extract(work_dir),
        }
    }
}

pub mod validation {
    use super::*;
    use edda_sandbox::DaggerSandbox;
    use std::pin::Pin;

    pub trait Validation {
        fn validate(
            &self,
            sandbox: &mut DaggerSandbox,
            work_dir: &str,
        ) -> impl Future<Output = Result<(), ValidationDetails>> + Send;

        fn docker_image(&self) -> String {
            "node:20-alpine3.22".to_string()
        }

        fn boxed(self) -> Box<dyn ValidationDyn>
        where
            Self: Sized + Send + Sync + 'static,
        {
            Box::new(self)
        }
    }

    pub trait ValidationDyn: Send + Sync {
        fn validate<'a>(
            &'a self,
            sandbox: &'a mut DaggerSandbox,
            work_dir: &'a str,
        ) -> Pin<Box<dyn Future<Output = Result<(), ValidationDetails>> + Send + 'a>>;

        fn docker_image(&self) -> String {
            "node:20-alpine3.22".to_string()
        }
    }

    impl<T: Validation + Send + Sync> ValidationDyn for T {
        fn validate<'a>(
            &'a self,
            sandbox: &'a mut DaggerSandbox,
            work_dir: &'a str,
        ) -> Pin<Box<dyn Future<Output = Result<(), ValidationDetails>> + Send + 'a>> {
            Box::pin(self.validate(sandbox, work_dir))
        }
    }

    pub struct ValidationTRPC;

    impl Validation for ValidationTRPC {
        async fn validate(
            &self,
            sandbox: &mut DaggerSandbox,
            work_dir: &str,
        ) -> Result<(), ValidationDetails> {
            let start_time = std::time::Instant::now();
            tracing::info!("Starting tRPC validation (build + tests + type checks)...");

            refresh_sandbox_files(sandbox, work_dir).await?;
            Self::run_build(sandbox).await?;
            Self::run_client_type_check(sandbox).await?;
            Self::run_tests(sandbox).await?;

            let duration = start_time.elapsed().as_secs_f64();
            tracing::info!(duration, "All tRPC validation checks passed");
            Ok(())
        }
    }

    impl ValidationTRPC {
        pub async fn run_build(sandbox: &mut DaggerSandbox) -> Result<(), ValidationDetails> {
            let start_time = std::time::Instant::now();
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

            let duration = start_time.elapsed().as_secs_f64();
            tracing::info!(duration, "Build passed");
            Ok(())
        }

        pub async fn run_client_type_check(
            sandbox: &mut DaggerSandbox,
        ) -> Result<(), ValidationDetails> {
            let start_time = std::time::Instant::now();
            let check_result = sandbox
                .exec("cd /app/client && npx tsc --noEmit")
                .await
                .map_err(|e| ValidationDetails {
                    exit_code: -1,
                    stdout: String::new(),
                    stderr: format!("Failed to run client type check: {}", e),
                })?;

            if check_result.exit_code != 0 {
                tracing::error!("Client type check failed: {:?}", check_result);
                return Err(ValidationDetails {
                    exit_code: check_result.exit_code,
                    stdout: check_result.stdout,
                    stderr: check_result.stderr,
                });
            }

            let duration = start_time.elapsed().as_secs_f64();
            tracing::info!(duration, "Client type check passed");
            Ok(())
        }

        pub async fn run_tests(sandbox: &mut DaggerSandbox) -> Result<(), ValidationDetails> {
            let start_time = std::time::Instant::now();
            let test_result =
                sandbox
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

            let duration = start_time.elapsed().as_secs_f64();
            tracing::info!(duration, "Tests passed");
            Ok(())
        }
    }

    pub struct ValidationCmd {
        pub command: String,
        pub docker_image: String,
    }

    impl Validation for ValidationCmd {
        async fn validate(
            &self,
            sandbox: &mut DaggerSandbox,
            work_dir: &str,
        ) -> Result<(), ValidationDetails> {
            let start_time = std::time::Instant::now();
            tracing::info!("Starting custom validation: {}", self.command);

            refresh_sandbox_files(sandbox, work_dir).await?;

            let result = sandbox
                .exec(&format!("cd /app && {}", self.command))
                .await
                .map_err(|e| ValidationDetails {
                    exit_code: -1,
                    stdout: String::new(),
                    stderr: format!("Failed to run validation command: {}", e),
                })?;

            if result.exit_code != 0 {
                tracing::error!("Validation command failed: {:?}", result);
                return Err(ValidationDetails {
                    exit_code: result.exit_code,
                    stdout: result.stdout,
                    stderr: result.stderr,
                });
            }

            let duration = start_time.elapsed().as_secs_f64();
            tracing::info!(duration, "Custom validation passed");
            Ok(())
        }

        fn docker_image(&self) -> String {
            self.docker_image.clone()
        }
    }

    // Helper functions (kept internal to validation module)
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
}

#[tool_handler]
impl ServerHandler for IOProvider {
    fn get_info(&self) -> ServerInfo {
        crate::mcp_helpers::internal_server_info()
    }
}
