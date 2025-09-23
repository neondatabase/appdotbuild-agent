use dabgent_agent::toolbox::Validator;
use dabgent_sandbox::SandboxDyn;
use eyre::Result;

pub struct DataAppsValidator;

impl Default for DataAppsValidator {
    fn default() -> Self {
        Self
    }
}

impl DataAppsValidator {
    pub fn new() -> Self {
        Self
    }

    async fn check_python_dependencies(&self, sandbox: &mut Box<dyn SandboxDyn>) -> Result<(), String> {
        tracing::info!("Starting Python dependencies check...");

        // Try to install dependencies - need to be in backend directory for uv sync
        let result = sandbox.exec("cd /app/backend && uv sync --dev")
            .await.map_err(|e| {
                let error = format!("Failed to run uv sync: {}", e);
                tracing::error!("{}", error);
                error
            })?;

        tracing::info!("uv sync result: exit_code={}, stdout={}, stderr={}", result.exit_code, result.stdout, result.stderr);

        if result.exit_code != 0 {
            let error_msg = format!(
                "Python dependency installation failed (exit code {}): stderr: {} stdout: {}",
                result.exit_code,
                result.stderr,
                result.stdout
            );
            tracing::info!("Python dependencies check failed: {}", error_msg);
            return Err(error_msg);
        }

        tracing::info!("Python dependencies check passed");
        Ok(())
    }


    async fn check_linting(&self, sandbox: &mut Box<dyn SandboxDyn>) -> Result<(), String> {
        tracing::info!("Starting linting check...");

        let result = sandbox.exec("cd /app/backend && uv run ruff check . --fix")
            .await.map_err(|e| {
                let error = format!("Failed to run linter: {}", e);
                tracing::error!("{}", error);
                error
            })?;

        if result.exit_code != 0 {
            let error_msg = format!(
                "Linting errors found (exit code {}): stderr: {} stdout: {}",
                result.exit_code,
                result.stderr,
                result.stdout
            );
            tracing::info!("Linting check failed: {}", error_msg);
            return Err(error_msg);
        }

        tracing::info!("Linting check passed");
        Ok(())
    }

    async fn check_frontend_build(&self, sandbox: &mut Box<dyn SandboxDyn>) -> Result<(), String> {
        tracing::info!("Starting frontend build check...");

        // Check if package.json exists
        let package_check = sandbox.read_file("/app/package.json").await;
        if package_check.is_err() {
            let error_msg = "package.json not found in project root".to_string();
            tracing::info!("Frontend build check failed: {}", error_msg);
            return Err(error_msg);
        }

        // Install npm dependencies
        let install_result = sandbox.exec("cd /app/frontend && npm ci")
            .await.map_err(|e| {
                let error = format!("Failed to install npm dependencies: {}", e);
                tracing::error!("{}", error);
                error
            })?;

        if install_result.exit_code != 0 {
            let error_msg = format!(
                "npm install failed (exit code {}): stderr: {} stdout: {}",
                install_result.exit_code,
                install_result.stderr,
                install_result.stdout
            );
            tracing::info!("Frontend build check failed: {}", error_msg);
            return Err(error_msg);
        }

        // Build frontend
        let build_result = sandbox.exec("cd /app/frontend && npm run build")
            .await.map_err(|e| {
                let error = format!("Failed to build frontend: {}", e);
                tracing::error!("{}", error);
                error
            })?;

        if build_result.exit_code != 0 {
            let error_msg = format!(
                "Frontend build failed (exit code {}): stderr: {} stdout: {}",
                build_result.exit_code,
                build_result.stderr,
                build_result.stdout
            );
            tracing::info!("Frontend build check failed: {}", error_msg);
            return Err(error_msg);
        }

        tracing::info!("Frontend build check passed");
        Ok(())
    }

    async fn check_tests(&self, sandbox: &mut Box<dyn SandboxDyn>) -> Result<(), String> {
        tracing::info!("Starting tests check...");

        let result = sandbox.exec("cd /app/backend && uv run pytest . -v")
            .await.map_err(|e| {
                let error = format!("Failed to run tests: {}", e);
                tracing::error!("{}", error);
                error
            })?;

        if result.exit_code != 0 {
            let error_msg = format!(
                "Tests failed (exit code {}): stderr: {} stdout: {}",
                result.exit_code,
                result.stderr,
                result.stdout
            );
            tracing::info!("Tests check failed: {}", error_msg);
            return Err(error_msg);
        }

        tracing::info!("Tests check passed");
        Ok(())
    }

}

impl Validator for DataAppsValidator {
    async fn run(&self, sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
        // Initial setup: ensure we're in the backend directory and sync dependencies
        match sandbox.exec("cd /app/backend && uv sync --dev").await {
            Ok(_) => (),
            Err(e) => return Ok(Err(format!("Failed to run uv sync: {}", e))),
        }
        tracing::info!("Sandbox is ready. Starting validation steps...");

        // Run all validation checks and collect results
        // FixMe: how to parallelize these?
        let deps_result = self.check_python_dependencies(sandbox).await;
        let tests_result = self.check_tests(sandbox).await;
        let linting_result = self.check_linting(sandbox).await;
        let frontend_result = self.check_frontend_build(sandbox).await;

        // Collect all errors
        let mut errors = Vec::new();

        if let Err(e) = deps_result {
            errors.push(format!("Dependencies: {}", e));
        }

        if let Err(e) = tests_result {
            errors.push(format!("Tests: {}", e));
        }

        if let Err(e) = linting_result {
            errors.push(format!("Linting: {}", e));
        }

        if let Err(e) = frontend_result {
            errors.push(format!("Frontend: {}", e));
        }

        if errors.is_empty() {
            tracing::info!("All validation checks passed");
            Ok(Ok(()))
        } else {
            let combined_error = errors.join("; ");
            tracing::info!("Validation failed with {} errors: {}", errors.len(), combined_error);
            Ok(Err(combined_error))
        }
    }
}
