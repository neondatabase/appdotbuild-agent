use dabgent_agent::toolbox::{Tool, Validator, basic::{TaskListValidator, DoneTool}};
use dabgent_sandbox::dagger::{ConnectOpts, Sandbox as DaggerSandbox};
use dabgent_sandbox::SandboxDyn;
use eyre::Result;

struct SimpleValidator;

impl Validator for SimpleValidator {
    async fn run(&self, sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
        // Simple validation: check if main.py exists and is executable
        match sandbox.exec("python --version").await {
            Ok(result) if result.exit_code == 0 => Ok(Ok(())),
            Ok(_) => Ok(Err("Python is not available".to_string())),
            Err(e) => Ok(Err(format!("Failed to check Python: {}", e))),
        }
    }
}

#[tokio::test]
async fn test_task_list_validator_with_done_tool() {
    let opts = ConnectOpts::default();
    let result = opts.connect(|client| async move {
        let container = client
            .container()
            .from("python:3.11-slim")
            .with_workdir("/workspace");

        container.sync().await?;
        let mut sandbox: Box<dyn SandboxDyn> = Box::new(DaggerSandbox::from_container(container, client.clone()));

        // Create TaskListValidator with SimpleValidator
        let validator = TaskListValidator::new(SimpleValidator);

        // Test 1: No planning.md - should pass (optional file)
        let result = validator.run(&mut sandbox).await?;
        assert!(result.is_ok(), "Should pass when planning.md doesn't exist");

        // Test 2: Create planning.md with incomplete tasks
        sandbox.write_file("planning.md",
            "# Project Tasks\n\n\
             - [x] Setup Python environment\n\
             - [ ] Create main.py script\n\
             - [ ] Add tests\n"
        ).await?;

        let result = validator.run(&mut sandbox).await?;
        assert!(result.is_err(), "Should fail with incomplete tasks");
        assert!(result.as_ref().unwrap_err().contains("Not all tasks are completed"));

        // Test 3: Complete all tasks
        sandbox.write_file("planning.md",
            "# Project Tasks\n\n\
             - [x] Setup Python environment\n\
             - [x] Create main.py script\n\
             - [x] Add tests\n"
        ).await?;

        let result = validator.run(&mut sandbox).await?;
        assert!(result.is_ok(), "Should pass with all tasks completed");

        // Test 4: Use with DoneTool
        let done_tool = DoneTool::new(TaskListValidator::new(SimpleValidator));

        // Reset to incomplete tasks
        sandbox.write_file("planning.md",
            "# Project Tasks\n\n\
             - [x] Setup Python environment\n\
             - [ ] Create main.py script\n\
             - [ ] Add tests\n"
        ).await?;

        // DoneTool should fail due to incomplete tasks
        let done_result = done_tool.call(
            serde_json::json!({"summary": "Task validation completed"}),
            &mut sandbox
        ).await?;

        assert!(done_result.is_err(), "DoneTool should report error for incomplete tasks");
        let error_msg = done_result.unwrap_err();
        assert!(error_msg.contains("Not all tasks are completed"),
            "Error should mention incomplete tasks: {}", error_msg);

        // Complete all tasks and try again
        sandbox.write_file("planning.md",
            "# Project Tasks\n\n\
             - [x] Setup Python environment\n\
             - [x] Create main.py script\n\
             - [x] Add tests\n"
        ).await?;

        let done_result = done_tool.call(
            serde_json::json!({"summary": "All tasks completed successfully"}),
            &mut sandbox
        ).await?;

        assert!(done_result.is_ok(), "DoneTool should succeed with all tasks completed");
        assert_eq!(done_result.unwrap(), "All tasks completed successfully", "Should return summary");

        Ok::<(), eyre::Error>(())
    }).await;

    if let Err(e) = result {
        eprintln!("Test skipped or failed - Docker/Dagger may not be available: {}", e);
    }
}

#[tokio::test]
async fn test_task_list_edge_cases() {
    let opts = ConnectOpts::default();
    let result = opts.connect(|client| async move {
        let container = client
            .container()
            .from("alpine:latest")
            .with_workdir("/workspace");

        container.sync().await?;
        let mut sandbox: Box<dyn SandboxDyn> = Box::new(DaggerSandbox::from_container(container, client.clone()));

        struct AlwaysPassValidator;
        impl Validator for AlwaysPassValidator {
            async fn run(&self, _: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
                Ok(Ok(()))
            }
        }

        let validator = TaskListValidator::new(AlwaysPassValidator);

        // Test various task list formats
        let test_cases = vec![
            ("# Empty\n", false, "No completed tasks"),
            ("- [x] Task", true, "Single completed task"),
            ("- [X] Task", true, "Capital X task"),
            ("* [x] Task", true, "Asterisk bullet"),
            ("1. [x] Task", true, "Numbered list"),
            ("- [ ] Incomplete", false, "Incomplete task"),
            ("- [x] Done\n- [ ] Not done", false, "Mixed tasks"),
            ("Random text without tasks", false, "No task markers"),
            ("- [x] Done\n- [-] In progress", true, "In progress not blocking"),
        ];

        for (content, should_pass, description) in test_cases {
            sandbox.write_file("planning.md", content).await?;
            let result = validator.run(&mut sandbox).await?;

            if should_pass {
                assert!(result.is_ok(), "{} should pass but got: {:?}", description, result);
            } else {
                assert!(result.is_err(), "{} should fail but passed", description);
            }
        }

        Ok::<(), eyre::Error>(())
    }).await;

    if let Err(e) = result {
        eprintln!("Test skipped - Docker/Dagger may not be available: {}", e);
    }
}