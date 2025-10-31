use crate::python_parser::{extract_function_signatures, generate_equivalence_tests, generate_rust_stubs};
use crate::template::{extract_template_files, TemplateMaturin};
use edda_sandbox::dagger::{ConnectOpts, Logger};
use edda_sandbox::{DaggerSandbox, Sandbox};
use eyre::Result;
use rmcp::handler::server::router::tool::ToolRouter;
use rmcp::handler::server::wrapper::Parameters;
use rmcp::model::{
    CallToolResult, Content, Implementation, ProtocolVersion, ServerCapabilities, ServerInfo,
};
use rmcp::{tool, tool_handler, tool_router, ErrorData, ServerHandler};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::io::ErrorKind;
use std::path::{Path, PathBuf};

#[derive(Clone)]
pub struct TranspilerProvider {
    tool_router: ToolRouter<Self>,
}

#[derive(Debug, Deserialize, Serialize, JsonSchema)]
pub struct ScaffoldMaturinArgs {
    /// Absolute path to the work directory for the Rust project
    pub work_dir: String,
    /// Python source code to analyze for function signatures
    pub python_source: String,
    /// Name of the Python module (for test generation)
    #[serde(default = "default_module_name")]
    pub python_module_name: String,
    /// If true, wipe the work directory before scaffolding
    #[serde(default)]
    pub force_rewrite: bool,
}

fn default_module_name() -> String {
    "original_module".to_string()
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ScaffoldMaturinResult {
    pub files_created: Vec<String>,
    pub work_dir: String,
    pub functions_found: Vec<String>,
    pub guidelines: String,
}

#[derive(Debug, Deserialize, Serialize, JsonSchema)]
pub struct ValidatePythonArgs {
    /// Absolute path to the Python project directory
    pub python_dir: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ValidatePythonResult {
    pub tests_exist: bool,
    pub tests_pass: bool,
    pub exit_code: Option<isize>,
    pub stdout: String,
    pub stderr: String,
}

#[derive(Debug, Deserialize, Serialize, JsonSchema)]
pub struct ValidateEquivalenceArgs {
    /// Absolute path to the Python project directory
    pub python_dir: String,
    /// Absolute path to the Rust project directory
    pub rust_dir: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ValidateEquivalenceResult {
    pub success: bool,
    pub message: String,
    pub python_result: Option<TestResult>,
    pub rust_result: Option<TestResult>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct TestResult {
    pub exit_code: isize,
    pub stdout: String,
    pub stderr: String,
}

#[tool_router]
impl TranspilerProvider {
    pub fn new() -> Result<Self> {
        Ok(Self {
            tool_router: Self::tool_router(),
        })
    }

    #[tool(
        name = "scaffold_maturin_project",
        description = "Initialize a maturin project structure for Python→Rust transpilation. Analyzes Python source code, creates Rust stubs with TODO comments, and provides comprehensive guidelines for implementing PyO3 bindings. The agent should then implement the Rust functions following the guidelines."
    )]
    pub async fn scaffold_maturin_project(
        &self,
        Parameters(args): Parameters<ScaffoldMaturinArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let work_path = PathBuf::from(&args.work_dir);

        // validate absolute path
        if !work_path.is_absolute() {
            return Err(ErrorData::invalid_params(
                format!(
                    "work_dir must be an absolute path, got: '{}'. Relative paths are not supported",
                    args.work_dir
                ),
                None,
            ));
        }

        // handle force rewrite
        if args.force_rewrite {
            match std::fs::remove_dir_all(&work_path) {
                Ok(_) => {}
                Err(err) if err.kind() == ErrorKind::NotFound => {}
                Err(err) => {
                    return Err(ErrorData::internal_error(
                        format!("failed to remove existing directory: {}", err),
                        None,
                    ))
                }
            }
        }

        // create work directory
        std::fs::create_dir_all(&work_path).map_err(|e| {
            ErrorData::internal_error(
                format!("failed to create work directory '{}': {}", work_path.display(), e),
                None,
            )
        })?;

        // extract template files
        let mut files = extract_template_files(&work_path).map_err(|e| {
            ErrorData::internal_error(format!("failed to extract template: {}", e), None)
        })?;

        // parse Python source for function signatures
        let functions = extract_function_signatures(&args.python_source).map_err(|e| {
            ErrorData::internal_error(format!("failed to parse Python source: {}", e), None)
        })?;

        let function_names: Vec<String> = functions.iter().map(|f| f.name.clone()).collect();

        // generate Rust stubs
        let rust_stubs = generate_rust_stubs(&functions);
        let lib_path = work_path.join("src/lib.rs");
        std::fs::write(&lib_path, rust_stubs).map_err(|e| {
            ErrorData::internal_error(format!("failed to write Rust stubs: {}", e), None)
        })?;
        files.push(lib_path);

        // generate equivalence tests
        let test_content = generate_equivalence_tests(&functions, &args.python_module_name);
        let test_path = work_path.join("tests/test_equivalence.py");
        std::fs::write(&test_path, test_content).map_err(|e| {
            ErrorData::internal_error(format!("failed to write test template: {}", e), None)
        })?;
        files.push(test_path);

        let guidelines = TemplateMaturin::guidelines();

        let result = ScaffoldMaturinResult {
            files_created: files.iter().map(|p| p.display().to_string()).collect(),
            work_dir: work_path.display().to_string(),
            functions_found: function_names,
            guidelines: guidelines.to_string(),
        };

        Ok(CallToolResult::success(vec![Content::text(format!(
            "Successfully scaffolded maturin project at {}\n\n\
             Functions found: {}\n\n\
             Files created:\n{}\n\n\
             IMPLEMENTATION GUIDELINES:\n\n{}",
            result.work_dir,
            result.functions_found.join(", "),
            result.files_created.join("\n"),
            result.guidelines
        ))]))
    }

    #[tool(
        name = "validate_python_tests",
        description = "Validate Python project by running tests in a sandbox. Checks if tests exist and pass. Returns detailed output for debugging. Use this to ensure Python tests are working before transpiling to Rust."
    )]
    pub async fn validate_python_tests(
        &self,
        Parameters(args): Parameters<ValidatePythonArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let python_path = PathBuf::from(&args.python_dir);

        if !python_path.is_absolute() {
            return Err(ErrorData::invalid_params(
                format!("python_dir must be an absolute path, got: '{}'", args.python_dir),
                None,
            ));
        }

        if !python_path.exists() {
            return Err(ErrorData::invalid_params(
                format!("python_dir does not exist: {}", python_path.display()),
                None,
            ));
        }

        let result = Self::validate_python_impl(&python_path)
            .await
            .map_err(|e| {
                ErrorData::internal_error(format!("validation failed: {}", e), None)
            })?;

        let display = if result.tests_pass {
            format!(
                "✓ Python tests passed\n\nOutput:\n{}",
                result.stdout
            )
        } else if !result.tests_exist {
            format!(
                "✗ No tests found in {}\n\nRun pytest with --collect-only to see available tests.\n\nOutput:\n{}",
                args.python_dir,
                result.stderr
            )
        } else {
            format!(
                "✗ Python tests failed (exit code: {})\n\nStdout:\n{}\n\nStderr:\n{}",
                result.exit_code.unwrap_or(-1),
                result.stdout,
                result.stderr
            )
        };

        Ok(CallToolResult::success(vec![Content::text(display)]))
    }

    #[tool(
        name = "validate_rust_equivalent",
        description = "Validate Rust implementation by building with maturin and running tests that compare Python and Rust outputs. Returns detailed comparison showing any differences. Use this iteratively until all tests pass."
    )]
    pub async fn validate_rust_equivalent(
        &self,
        Parameters(args): Parameters<ValidateEquivalenceArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let python_path = PathBuf::from(&args.python_dir);
        let rust_path = PathBuf::from(&args.rust_dir);

        if !python_path.is_absolute() {
            return Err(ErrorData::invalid_params(
                format!("python_dir must be an absolute path, got: '{}'", args.python_dir),
                None,
            ));
        }

        if !rust_path.is_absolute() {
            return Err(ErrorData::invalid_params(
                format!("rust_dir must be an absolute path, got: '{}'", args.rust_dir),
                None,
            ));
        }

        let result = Self::validate_equivalence_impl(&python_path, &rust_path)
            .await
            .map_err(|e| {
                ErrorData::internal_error(format!("validation failed: {}", e), None)
            })?;

        let display = format_equivalence_result(&result);

        Ok(CallToolResult::success(vec![Content::text(display)]))
    }

    /// Internal implementation for Python validation
    async fn validate_python_impl(python_dir: &Path) -> Result<ValidatePythonResult> {
        let (tx, rx) = tokio::sync::oneshot::channel();
        let python_dir_str = python_dir.display().to_string();

        let opts = ConnectOpts::default()
            .with_logger(Logger::Silent)
            .with_execute_timeout(Some(300));

        opts.connect(move |client| async move {
            let container = client
                .container()
                .from("python:3.11-slim")
                .with_exec(vec!["pip", "install", "pytest", "pytest-cov"])
                .with_directory("/app", client.host().directory(python_dir_str));

            let mut sandbox = DaggerSandbox::from_container(container, client);

            // Check if tests exist
            let collect_result = sandbox.exec("cd /app && python -m pytest --collect-only").await;

            let tests_exist = collect_result.as_ref().map_or(false, |r| r.exit_code == 0);

            // Run tests if they exist
            let test_result = if tests_exist {
                sandbox.exec("cd /app && python -m pytest -v").await
            } else {
                collect_result
            };

            let result = match test_result {
                Ok(output) => ValidatePythonResult {
                    tests_exist,
                    tests_pass: output.exit_code == 0,
                    exit_code: Some(output.exit_code),
                    stdout: output.stdout,
                    stderr: output.stderr,
                },
                Err(e) => ValidatePythonResult {
                    tests_exist: false,
                    tests_pass: false,
                    exit_code: None,
                    stdout: String::new(),
                    stderr: format!("Failed to run pytest: {}", e),
                },
            };

            let _ = tx.send(result);
            Ok(())
        })
        .await?;

        rx.await
            .map_err(|_| eyre::eyre!("validation task was cancelled"))
    }

    /// Internal implementation for equivalence validation
    async fn validate_equivalence_impl(
        python_dir: &Path,
        rust_dir: &Path,
    ) -> Result<ValidateEquivalenceResult> {
        let (tx, rx) = tokio::sync::oneshot::channel();
        let python_dir_str = python_dir.display().to_string();
        let rust_dir_str = rust_dir.display().to_string();

        let opts = ConnectOpts::default()
            .with_logger(Logger::Silent)
            .with_execute_timeout(Some(600));

        opts.connect(move |client| async move {
            // Use Rust image with Python support
            let container = client
                .container()
                .from("rust:1.83-slim")
                .with_exec(vec!["apt-get", "update"])
                .with_exec(vec![
                    "apt-get",
                    "install",
                    "-y",
                    "python3",
                    "python3-pip",
                    "python3-venv",
                    "python3-dev",
                    "build-essential",
                ])
                .with_directory("/python_project", client.host().directory(python_dir_str))
                .with_directory("/rust_project", client.host().directory(rust_dir_str));

            let mut sandbox = DaggerSandbox::from_container(container, client);

            // Run Python tests (baseline)
            let py_result = sandbox
                .exec("cd /python_project && pip3 install pytest && python3 -m pytest -v")
                .await;

            // Build Rust with maturin and run equivalence tests
            let rust_result = sandbox
                .exec(
                    "cd /rust_project && \
                     pip3 install maturin pytest && \
                     maturin develop && \
                     python3 -m pytest -v",
                )
                .await;

            let result = match (py_result, rust_result) {
                (Ok(py), Ok(rust)) => {
                    let success = py.exit_code == 0 && rust.exit_code == 0;
                    let message = if success {
                        "All tests passed! Rust implementation matches Python behavior.".to_string()
                    } else {
                        "Tests failed. See details below.".to_string()
                    };

                    ValidateEquivalenceResult {
                        success,
                        message,
                        python_result: Some(TestResult {
                            exit_code: py.exit_code,
                            stdout: py.stdout,
                            stderr: py.stderr,
                        }),
                        rust_result: Some(TestResult {
                            exit_code: rust.exit_code,
                            stdout: rust.stdout,
                            stderr: rust.stderr,
                        }),
                    }
                }
                (Err(e), _) => ValidateEquivalenceResult {
                    success: false,
                    message: format!("Python tests failed to run: {}", e),
                    python_result: None,
                    rust_result: None,
                },
                (_, Err(e)) => ValidateEquivalenceResult {
                    success: false,
                    message: format!("Rust build/tests failed: {}", e),
                    python_result: None,
                    rust_result: None,
                },
            };

            let _ = tx.send(result);
            Ok(())
        })
        .await?;

        rx.await
            .map_err(|_| eyre::eyre!("validation task was cancelled"))
    }
}

fn format_equivalence_result(result: &ValidateEquivalenceResult) -> String {
    if result.success {
        return format!("✓ {}\n\nAll equivalence tests passed!", result.message);
    }

    let mut output = format!("✗ {}\n\n", result.message);

    if let Some(py) = &result.python_result {
        output.push_str(&format!(
            "PYTHON TESTS (exit code {}):\n{}\n\n",
            py.exit_code,
            if !py.stdout.is_empty() {
                &py.stdout
            } else {
                &py.stderr
            }
        ));
    }

    if let Some(rust) = &result.rust_result {
        output.push_str(&format!(
            "RUST TESTS (exit code {}):\n{}\n{}\n\n",
            rust.exit_code, rust.stdout, rust.stderr
        ));
    }

    output.push_str(
        "Fix the Rust implementation based on the test failures above, then run validate_rust_equivalent again.",
    );

    output
}

#[tool_handler]
impl ServerHandler for TranspilerProvider {
    fn get_info(&self) -> ServerInfo {
        ServerInfo {
            protocol_version: ProtocolVersion::V_2024_11_05,
            capabilities: ServerCapabilities::builder().enable_tools().build(),
            server_info: Implementation {
                name: "edda-transpiler".to_string(),
                version: env!("CARGO_PKG_VERSION").to_string(),
                title: Some("Edda Transpiler".to_string()),
                website_url: None,
                icons: None,
            },
            instructions: Some(
                "MCP server for Python→Rust transpilation. Provides scaffolding, validation, and guidelines for converting Python code to Rust with PyO3 bindings.".to_string(),
            ),
        }
    }
}
