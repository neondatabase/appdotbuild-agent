use crate::toolbox;
use dabgent_sandbox::SandboxDyn;
use eyre::Result;

/// Default validator for Python projects using uv
#[derive(Clone, Debug)]
pub struct PythonUvValidator;

impl toolbox::Validator for PythonUvValidator {
    async fn run(&self, sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
        let result = sandbox.exec("uv run main.py").await?;
        Ok(match result.exit_code {
            0 | 124 => Ok(()), // 0 = success, 124 = timeout (considered success)
            code => Err(format!(
                "Validation failed with exit code: {}\nstdout: {}\nstderr: {}",
                code, result.stdout, result.stderr
            )),
        })
    }
}

/// Custom validator that runs a specific command
#[derive(Clone, Debug)]
pub struct CustomValidator {
    command: String,
}

impl CustomValidator {
    pub fn new(command: impl Into<String>) -> Self {
        Self {
            command: command.into(),
        }
    }
}

impl toolbox::Validator for CustomValidator {
    async fn run(&self, sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
        let result = sandbox.exec(&self.command).await?;
        Ok(match result.exit_code {
            0 => Ok(()),
            code => Err(format!(
                "Command '{}' failed with exit code: {}\nstdout: {}\nstderr: {}",
                self.command, code, result.stdout, result.stderr
            )),
        })
    }
}

/// No-op validator for cases where validation is not needed
#[derive(Clone, Debug)]
pub struct NoOpValidator;

impl toolbox::Validator for NoOpValidator {
    async fn run(&self, _sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
        Ok(Ok(()))
    }
}

/// Validator that checks if specific files exist
#[derive(Clone, Debug)]
pub struct FileExistsValidator {
    files: Vec<String>,
    working_dir: String,
}

impl FileExistsValidator {
    pub fn new(files: Vec<String>) -> Self {
        Self {
            files,
            working_dir: "/app".to_string(),
        }
    }

    pub fn with_working_dir(mut self, dir: impl Into<String>) -> Self {
        self.working_dir = dir.into();
        self
    }
}

impl toolbox::Validator for FileExistsValidator {
    async fn run(&self, sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
        let files = sandbox.list_directory(&self.working_dir).await?;
        
        let mut missing_files = Vec::new();
        for required_file in &self.files {
            if !files.contains(required_file) {
                missing_files.push(required_file.clone());
            }
        }
        
        Ok(if missing_files.is_empty() {
            Ok(())
        } else {
            Err(format!("Missing required files: {:?}", missing_files))
        })
    }
}

/// Validator that runs a health check command
#[derive(Clone, Debug)]
pub struct HealthCheckValidator {
    command: String,
    expected_output: Option<String>,
    timeout_ok: bool,
}

impl HealthCheckValidator {
    pub fn new(command: impl Into<String>) -> Self {
        Self {
            command: command.into(),
            expected_output: None,
            timeout_ok: true,
        }
    }

    pub fn with_expected_output(mut self, output: impl Into<String>) -> Self {
        self.expected_output = Some(output.into());
        self
    }

    pub fn timeout_is_failure(mut self) -> Self {
        self.timeout_ok = false;
        self
    }
}

impl toolbox::Validator for HealthCheckValidator {
    async fn run(&self, sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
        let result = sandbox.exec(&self.command).await?;
        
        // Check exit code
        let exit_ok = match result.exit_code {
            0 => true,
            124 if self.timeout_ok => true, // Timeout might be ok for long-running services
            _ => false,
        };
        
        if !exit_ok {
            return Ok(Err(format!(
                "Health check '{}' failed with exit code: {}\nstdout: {}\nstderr: {}",
                self.command, result.exit_code, result.stdout, result.stderr
            )));
        }
        
        // Check expected output if specified
        if let Some(expected) = &self.expected_output {
            if !result.stdout.contains(expected) {
                return Ok(Err(format!(
                    "Health check '{}' output doesn't contain expected text '{}'\nActual stdout: {}",
                    self.command, expected, result.stdout
                )));
            }
        }
        
        Ok(Ok(()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validators_construction() {
        // Test that validators can be constructed
        let _python_validator = PythonUvValidator;
        let _custom_validator = CustomValidator::new("echo test");
        let _noop_validator = NoOpValidator;
        let _file_validator = FileExistsValidator::new(vec!["test.py".to_string()]);
        let _health_validator = HealthCheckValidator::new("echo test")
            .with_expected_output("test")
            .timeout_is_failure();
        
        // Test file validator with custom working dir
        let _file_validator_custom = FileExistsValidator::new(vec!["main.py".to_string()])
            .with_working_dir("/custom/dir");
    }
}
