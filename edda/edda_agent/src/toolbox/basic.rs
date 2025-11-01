// NOTE: These are sandbox-based tools for event-sourced agents.
// For local I/O tools (used by MCP), see edda_mcp/src/providers/local_io.rs
// TODO: Consider migrating to a shared edda_tools crate in the future for consistency,
// though the sandbox vs. host filesystem difference may warrant keeping them separate.

use super::{Tool, Validator, ValidatorDyn};
use edda_sandbox::{DaggerSandbox, Sandbox};
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
        sandbox: &mut DaggerSandbox,
    ) -> Result<Result<Self::Output, Self::Error>> {
        let result = sandbox.exec(&args.command).await?;
        match result.exit_code {
            0 => Ok(Ok(result.stdout)),
            _ => Ok(Err(format!("Error:\n{}\n{}", result.stderr, result.stdout))),
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
        sandbox: &mut DaggerSandbox,
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

    fn needs_replay(&self) -> bool {
        false
    }

    async fn call(
        &self,
        args: Self::Args,
        sandbox: &mut DaggerSandbox,
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

    fn needs_replay(&self) -> bool {
        false
    }

    async fn call(
        &self,
        args: Self::Args,
        sandbox: &mut DaggerSandbox,
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
        sandbox: &mut DaggerSandbox,
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
        sandbox: &mut DaggerSandbox,
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

    fn needs_replay(&self) -> bool {
        false
    }

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
        sandbox: &mut DaggerSandbox,
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
