use super::{Tool, Validator, ValidatorDyn};
use dabgent_sandbox::SandboxDyn;
use eyre::Result;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BashArgs {
    pub command: String,
}

#[derive(Clone)]
pub struct Bash;

impl Tool for Bash {
    type Args = BashArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "bash".to_owned()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "Run a bash command".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to run in the shell",
                    }
                },
                "required": ["command"],
            }),
        }
    }

    async fn call(
        &self,
        args: Self::Args,
        sandbox: &mut Box<dyn SandboxDyn>,
    ) -> Result<Result<Self::Output, Self::Error>> {
        let result = sandbox.exec(&args.command).await?;
        match result.exit_code {
            0 => Ok(Ok(result.stdout)),
            _ => Ok(Err(format!(
                "Error:\n{}\n{}",
                result.stderr, result.stdout
            ))),
        }
    }
}

#[derive(Clone)]
pub struct WriteFile;

#[derive(Serialize, Deserialize)]
pub struct WriteFileArgs {
    pub path: String,
    pub contents: String,
}

impl Tool for WriteFile {
    type Args = WriteFileArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "write_file".to_owned()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: "write_file".to_string(),
            description: "Write content to a file".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file",
                    },
                    "contents": {
                        "type": "string",
                        "description": "Content to write to the file",
                    }
                },
                "required": ["path", "contents"],
            }),
        }
    }

    async fn call(
        &self,
        args: Self::Args,
        sandbox: &mut Box<dyn SandboxDyn>,
    ) -> Result<Result<Self::Output, Self::Error>> {
        let WriteFileArgs { path, contents } = args;
        match sandbox.write_file(&path, &contents).await {
            Ok(_) => Ok(Ok("success".to_string())),
            Err(e) => Ok(Err(format!("Failed to write file '{}': {}", path, e))),
        }
    }
}

#[derive(Clone)]
pub struct ReadFile;

#[derive(Serialize, Deserialize)]
pub struct ReadFileArgs {
    pub path: String,
}

impl Tool for ReadFile {
    type Args = ReadFileArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "read_file".to_owned()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "Read a file from the sandbox".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read",
                    }
                },
                "required": ["path"],
            }),
        }
    }

    fn needs_replay(&self) -> bool { false }

    async fn call(
        &self,
        args: Self::Args,
        sandbox: &mut Box<dyn SandboxDyn>,
    ) -> Result<Result<Self::Output, Self::Error>> {
        match sandbox.read_file(&args.path).await {
            Ok(content) => Ok(Ok(content)),
            Err(e) => Ok(Err(format!("Failed to read file: {}", e))),
        }
    }
}

#[derive(Clone)]
pub struct LsDir;

#[derive(Serialize, Deserialize)]
pub struct LsDirArgs {
    pub path: String,
}

impl Tool for LsDir {
    type Args = LsDirArgs;
    type Output = Vec<String>;
    type Error = String;

    fn name(&self) -> String {
        "ls_dir".to_owned()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "List directory contents".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list",
                    }
                },
                "required": ["path"],
            }),
        }
    }

    fn needs_replay(&self) -> bool { false }

    async fn call(
        &self,
        args: Self::Args,
        sandbox: &mut Box<dyn SandboxDyn>,
    ) -> Result<Result<Self::Output, Self::Error>> {
        match sandbox.list_directory(&args.path).await {
            Ok(entries) => Ok(Ok(entries)),
            Err(e) => Ok(Err(format!("Failed to list directory: {}", e))),
        }
    }
}

#[derive(Clone)]
pub struct RmFile;

#[derive(Serialize, Deserialize)]
pub struct RmFileArgs {
    pub path: String,
}

impl Tool for RmFile {
    type Args = RmFileArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "rm_file".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "Remove a file".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to remove",
                    }
                },
                "required": ["path"],
            }),
        }
    }

    async fn call(
        &self,
        args: Self::Args,
        sandbox: &mut Box<dyn SandboxDyn>,
    ) -> eyre::Result<Result<Self::Output, Self::Error>> {
        match sandbox.delete_file(&args.path).await {
            Ok(_) => Ok(Ok("success".to_string())),
            Err(e) => Ok(Err(format!("Failed to delete file '{}': {}", args.path, e))),
        }
    }
}

#[derive(Clone)]
pub struct EditFile;

#[derive(Serialize, Deserialize)]
pub struct EditFileArgs {
    pub path: String,
    pub find: String,
    pub replace: String,
}

impl Tool for EditFile {
    type Args = EditFileArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "edit_file".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "Edit a file by replacing text".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file",
                    },
                    "find": {
                        "type": "string",
                        "description": "Text to find in the file",
                    },
                    "replace": {
                        "type": "string",
                        "description": "Text to replace with",
                    }
                },
                "required": ["path", "find", "replace"],
            }),
        }
    }

    async fn call(
        &self,
        args: Self::Args,
        sandbox: &mut Box<dyn SandboxDyn>,
    ) -> eyre::Result<Result<Self::Output, Self::Error>> {
        let EditFileArgs {
            path,
            find,
            replace,
        } = args;
        let contents = match sandbox.read_file(&path).await {
            Ok(content) => content,
            Err(e) => return Ok(Err(format!("Failed to read file '{}': {}", path, e))),
        };
        match contents.matches(&find).count() {
            1 => {
                let contents = contents.replace(&find, &replace);
                match sandbox.write_file(&path, &contents).await {
                    Ok(_) => Ok(Ok("success".to_string())),
                    Err(e) => Ok(Err(format!("Failed to write file '{}': {}", path, e))),
                }
            }
            num => Ok(Err(format!("Error: found {num} matches, expected 1"))),
        }
    }
}

pub struct DoneTool {
    validator: Box<dyn ValidatorDyn>,
}

impl DoneTool {
    pub fn new<T: Validator + Send + Sync + 'static>(validator: T) -> Self {
        Self {
            validator: validator.boxed(),
        }
    }
}

impl Tool for DoneTool {
    type Args = serde_json::Value;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "done".to_string()
    }

    fn needs_replay(&self) -> bool { false }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "Run checks, if successful mark task as finished".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {},
            }),
        }
    }

    async fn call(
        &self,
        _args: Self::Args,
        sandbox: &mut Box<dyn SandboxDyn>,
    ) -> eyre::Result<eyre::Result<Self::Output, Self::Error>> {
        match self.validator.run(sandbox).await {
            Ok(result) => Ok(match result {
                Ok(_) => Ok("success".to_string()),
                Err(err) => Err(format!("validation error: {}", err)),
            }),
            Err(e) => Ok(Err(format!("validator failed: {}", e))),
        }
    }
}

pub trait TaskList: Send + Sync {
    fn update(&self, current_content: String, instruction: String) -> Result<String>;
}

pub struct TaskListTool<T: TaskList> {
    task_list: T,
    read_file: ReadFile,
    write_file: WriteFile,
}

impl<T: TaskList> TaskListTool<T> {
    pub fn new(task_list: T) -> Self {
        Self {
            task_list,
            read_file: ReadFile,
            write_file: WriteFile,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskListArgs {
    pub instruction: String,
}

impl<T: TaskList> Tool for TaskListTool<T> {
    type Args = TaskListArgs;
    type Output = String;
    type Error = String;

    fn name(&self) -> String {
        "update_task_list".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "Update the planning.md task list file".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "Instructions for updating the task list (e.g., 'mark task X as complete', 'add new task Y')",
                    }
                },
                "required": ["instruction"],
            }),
        }
    }

    async fn call(
        &self,
        args: Self::Args,
        sandbox: &mut Box<dyn SandboxDyn>,
    ) -> Result<Result<Self::Output, Self::Error>> {
        // Read current planning.md file using ReadFile tool
        let read_args = ReadFileArgs {
            path: "planning.md".to_string(),
        };

        let current_content = match self.read_file.call(read_args, sandbox).await {
            Ok(Ok(content)) => content,
            Ok(Err(_)) | Err(_) => "# Planning\n\nNo tasks yet.\n".to_string(),
        };

        // Update content through TaskList trait
        let updated_content = match self.task_list.update(current_content, args.instruction.clone()) {
            Ok(content) => content,
            Err(e) => return Ok(Err(format!("Failed to update task list: {}", e))),
        };

        // Write updated content back using WriteFile tool
        let write_args = WriteFileArgs {
            path: "planning.md".to_string(),
            contents: updated_content,
        };

        match self.write_file.call(write_args, sandbox).await {
            Ok(Ok(_)) => Ok(Ok(format!("Task list updated: {}", args.instruction))),
            Ok(Err(e)) => Ok(Err(format!("Failed to write planning.md: {}", e))),
            Err(e) => Ok(Err(format!("Failed to write planning.md: {}", e))),
        }
    }
}

pub fn toolset<T: Validator + Send + Sync + 'static>(validator: T) -> Vec<Box<dyn super::ToolDyn>> {
    vec![
        Box::new(Bash),
        Box::new(WriteFile),
        Box::new(ReadFile),
        Box::new(LsDir),
        Box::new(RmFile),
        Box::new(EditFile),
        Box::new(DoneTool::new(validator)),
    ]
}

pub struct TaskListValidator<V: Validator> {
    inner_validator: V,
}

impl<V: Validator> TaskListValidator<V> {
    pub fn new(inner_validator: V) -> Self {
        Self { inner_validator }
    }
}

impl<V: Validator + Send + Sync> Validator for TaskListValidator<V> {
    async fn run(&self, sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
        match sandbox.read_file("planning.md").await {
            Ok(content) => {
                // Check for incomplete tasks with various formats
                let has_incomplete = content.contains("[ ]");

                // Check for completed tasks with various formats
                let has_completed = content.contains("[x]") || content.contains("[X]");

                if has_incomplete {
                    return Ok(Err("Not all tasks are completed. Please complete all tasks in planning.md before marking as done.".to_string()));
                }

                if !has_completed {
                    return Ok(Err("No completed tasks found in planning.md. Please add and complete tasks before marking as done.".to_string()));
                }
            }
            Err(_) => {
                // If planning.md doesn't exist, that's okay - continue with inner validator
            }
        }

        self.inner_validator.run(sandbox).await
    }
}

pub fn toolset_with_tasklist<V: Validator + Send + Sync + 'static, T: TaskList + 'static>(
    validator: V,
    task_list: T,
) -> Vec<Box<dyn super::ToolDyn>> {
    // Wrap the validator with TaskListValidator to ensure tasks are checked
    let task_list_validator = TaskListValidator::new(validator);

    vec![
        Box::new(Bash),
        Box::new(ReadFile),
        Box::new(EditFile),
        Box::new(TaskListTool::new(task_list)),
        Box::new(DoneTool::new(task_list_validator)),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};

    struct MockTaskList {
        update_fn: Arc<Mutex<dyn FnMut(String) -> String + Send>>,
    }

    impl MockTaskList {
        fn new<F>(f: F) -> Self
        where
            F: FnMut(String) -> String + Send + 'static,
        {
            Self {
                update_fn: Arc::new(Mutex::new(f)),
            }
        }
    }

    impl TaskList for MockTaskList {
        fn update(&self, current_content: String, _instruction: String) -> Result<String> {
            let mut f = self.update_fn.lock().unwrap();
            Ok(f(current_content))
        }
    }

    #[tokio::test]
    async fn test_task_list_validator() {
        use dabgent_sandbox::dagger::{ConnectOpts, Sandbox as DaggerSandbox};

        let opts = ConnectOpts::default();
        let result = opts.connect(|client| async move {
            let container = client
                .container()
                .from("python:3.11-slim")
                .with_workdir("/workspace");

            container.sync().await?;
            let mut sandbox: Box<dyn SandboxDyn> = Box::new(DaggerSandbox::from_container(container, client.clone()));

            // Create a mock inner validator that always passes
            struct AlwaysPassValidator;
            impl Validator for AlwaysPassValidator {
                async fn run(&self, _sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
                    Ok(Ok(()))
                }
            }

            let task_list_validator = TaskListValidator::new(AlwaysPassValidator);

            // Test 1: No planning.md file - should pass (file is optional)
            let result = Validator::run(&task_list_validator, &mut sandbox).await?;
            assert!(result.is_ok(), "Should pass when planning.md doesn't exist");

            // Test 2: planning.md with incomplete tasks - should fail
            sandbox.write_file("planning.md", "# Tasks\n- [ ] Task 1\n- [x] Task 2").await?;
            let result = Validator::run(&task_list_validator, &mut sandbox).await?;
            assert!(result.is_err(), "Should fail when there are incomplete tasks");
            assert!(result.unwrap_err().contains("Not all tasks are completed"));

            // Test 3: planning.md with all tasks completed - should pass
            sandbox.write_file("planning.md", "# Tasks\n- [x] Task 1\n- [x] Task 2").await?;
            let result = Validator::run(&task_list_validator, &mut sandbox).await?;
            assert!(result.is_ok(), "Should pass when all tasks are completed");

            // Test 4: planning.md with no tasks - should fail
            sandbox.write_file("planning.md", "# Tasks\nNo tasks defined yet").await?;
            let result = Validator::run(&task_list_validator, &mut sandbox).await?;
            assert!(result.is_err(), "Should fail when no tasks are defined");
            assert!(result.unwrap_err().contains("No completed tasks found"));

            // Test with inner validator that fails
            struct AlwaysFailValidator;
            impl Validator for AlwaysFailValidator {
                async fn run(&self, _sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
                    Ok(Err("Inner validation failed".to_string()))
                }
            }

            let task_list_validator_fail = TaskListValidator::new(AlwaysFailValidator);

            // Test 5: All tasks completed but inner validator fails - should fail
            sandbox.write_file("planning.md", "# Tasks\n- [x] Task 1\n- [x] Task 2").await?;
            let result = Validator::run(&task_list_validator_fail, &mut sandbox).await?;
            assert!(result.is_err(), "Should fail when inner validator fails");
            assert_eq!(result.unwrap_err(), "Inner validation failed");

            Ok::<(), eyre::Error>(())
        }).await;

        if result.is_err() {
            eprintln!("Skipping test - Docker/Dagger not available");
        }
    }

    #[tokio::test]
    async fn test_tasklist_tool() {
        use dabgent_sandbox::dagger::{ConnectOpts, Sandbox as DaggerSandbox};

        // Skip test if Docker/Dagger not available
        let opts = ConnectOpts::default();
        let result = opts.connect(|client| async move {
            // Create a simple container for testing
            let container = client
                .container()
                .from("alpine:latest")
                .with_exec(vec!["sh", "-c", "echo 'test environment ready'"]);

            container.sync().await?;
            let mut sandbox: Box<dyn SandboxDyn> = Box::new(DaggerSandbox::from_container(container, client.clone()));

            // Create mock task list that adds "- Task completed" to content
            let mock_tasklist = MockTaskList::new(|content| {
                format!("{}\n- Task completed", content)
            });

            let tool = TaskListTool::new(mock_tasklist);

            // Write initial file
            sandbox.write_file("planning.md", "# Planning\n\nNo tasks yet.\n").await.unwrap();

            // Test with existing file
            let args = TaskListArgs {
                instruction: "Mark first task as complete".to_string(),
            };

            let result = tool.call(args, &mut sandbox).await.unwrap();
            assert!(result.is_ok());

            // Verify file was updated
            let content = sandbox.read_file("planning.md").await.unwrap();
            assert!(content.contains("# Planning"));
            assert!(content.contains("- Task completed"));

            // Test with existing file again
            let args2 = TaskListArgs {
                instruction: "Add another task".to_string(),
            };

            let result2 = tool.call(args2, &mut sandbox).await.unwrap();
            assert!(result2.is_ok());

            // Verify content was updated
            let content2 = sandbox.read_file("planning.md").await.unwrap();
            assert_eq!(content2.matches("- Task completed").count(), 2);

            Ok::<(), eyre::Error>(())
        }).await;

        if result.is_err() {
            eprintln!("Skipping test - Docker/Dagger not available");
        }
    }
}
