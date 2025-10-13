use crate::tool::{CtxProvider, Tool};
use dabgent_sandbox::{DaggerSandbox, Sandbox, SandboxHandle};
use eyre::Result;
use serde::{Deserialize, Serialize};
use std::pin::Pin;

#[derive(Clone)]
pub struct TemplateConfig {
    pub host_dir: String,
    pub dockerfile: String,
    pub template_path: Option<String>,
    pub template_base_path: String,
}

impl TemplateConfig {
    pub fn new(host_dir: String, dockerfile: String) -> Self {
        Self {
            host_dir,
            dockerfile,
            template_path: None,
            template_base_path: "/app".to_string(),
        }
    }

    pub fn with_template(mut self, template_path: String) -> Self {
        self.template_path = Some(template_path);
        self
    }

    pub fn with_template_base_path(mut self, base_path: String) -> Self {
        self.template_base_path = base_path;
        self
    }

    pub fn default_dir<T: AsRef<str>>(host_dir: T) -> Self {
        Self {
            host_dir: host_dir.as_ref().to_string(),
            dockerfile: "Dockerfile".to_string(),
            template_path: None,
            template_base_path: "/app".to_string(),
        }
    }
}

pub struct SandboxCtx {
    sandbox: DaggerSandbox,
}

#[derive(Clone)]
pub struct SandboxProvider {
    pub config: TemplateConfig,
    pub dagger: SandboxHandle,
}

impl SandboxProvider {
    async fn get_sandbox(&self, aggregate_id: &str) -> Result<DaggerSandbox> {
        match self.dagger.get(aggregate_id).await? {
            Some(sandbox) => Ok(sandbox),
            None => {
                tracing::info!(
                    "Creating new sandbox for aggregate_id: {} from directory: {}, dockerfile: {}",
                    aggregate_id,
                    self.config.host_dir,
                    self.config.dockerfile
                );
                let mut sandbox = self
                    .dagger
                    .create_from_directory(
                        aggregate_id,
                        &self.config.host_dir,
                        &self.config.dockerfile,
                        vec![],
                    )
                    .await?;

                if let Some(template_path) = &self.config.template_path {
                    tracing::info!(
                        "Seeding template from: {} into base path: {}",
                        template_path,
                        self.config.template_base_path
                    );

                    let template_files = crate::sandbox_seed::collect_template_files(
                        std::path::Path::new(template_path),
                        &self.config.template_base_path,
                    )?;

                    let hash = crate::sandbox_seed::compute_template_hash(&template_files.files);

                    let files = template_files
                        .files
                        .iter()
                        .map(|(p, c)| (p.as_str(), c.as_str()))
                        .collect();
                    sandbox.write_files(files).await?;

                    tracing::info!(
                        "Template seeded successfully: {} files written, hash: {}",
                        template_files.files.len(),
                        hash
                    );
                }
                Ok(sandbox)
            }
        }
    }
}

impl CtxProvider for SandboxProvider {
    type Context = SandboxCtx;

    async fn get_context(&self, aggregate_id: &str) -> Result<Self::Context> {
        let sandbox = self.get_sandbox(aggregate_id).await?;
        Ok(SandboxCtx { sandbox })
    }

    async fn put_context(&self, aggregate_id: &str, context: Self::Context) -> eyre::Result<()> {
        self.dagger.set(aggregate_id, context.sandbox).await?;
        Ok(())
    }
}

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
    type Context = SandboxCtx;

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
        ctx: &mut Self::Context,
        args: &Self::Args,
    ) -> Result<Self::Output, Self::Error> {
        let result = ctx
            .sandbox
            .exec(&args.command)
            .await
            .map_err(|e| e.to_string())?;
        match result.exit_code {
            0 => Ok(result.stdout),
            _ => Err(format!("Error:\n{}\n{}", result.stderr, result.stdout)),
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
    type Context = SandboxCtx;

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
        ctx: &mut SandboxCtx,
        args: &Self::Args,
    ) -> Result<Self::Output, Self::Error> {
        let WriteFileArgs { path, contents } = args;
        match ctx.sandbox.write_file(&path, &contents).await {
            Ok(_) => Ok("success".to_string()),
            Err(e) => Err(format!("Failed to write file '{}': {}", path, e)),
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
    type Context = SandboxCtx;

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

    async fn call(
        &self,
        ctx: &mut SandboxCtx,
        args: &Self::Args,
    ) -> Result<Self::Output, Self::Error> {
        match ctx.sandbox.read_file(&args.path).await {
            Ok(content) => Ok(content),
            Err(e) => Err(format!("Failed to read file: {}", e)),
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
    type Context = SandboxCtx;

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

    async fn call(
        &self,
        ctx: &mut SandboxCtx,
        args: &Self::Args,
    ) -> Result<Self::Output, Self::Error> {
        match ctx.sandbox.list_directory(&args.path).await {
            Ok(entries) => Ok(entries),
            Err(e) => Err(format!("Failed to list directory: {}", e)),
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
    type Context = SandboxCtx;

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
        ctx: &mut SandboxCtx,
        args: &Self::Args,
    ) -> Result<Self::Output, Self::Error> {
        match ctx.sandbox.delete_file(&args.path).await {
            Ok(_) => Ok("success".to_string()),
            Err(e) => Err(format!("Failed to delete file '{}': {}", args.path, e)),
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
    type Context = SandboxCtx;

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
        ctx: &mut SandboxCtx,
        args: &Self::Args,
    ) -> Result<Self::Output, Self::Error> {
        let EditFileArgs {
            path,
            find,
            replace,
        } = args;
        let contents = match ctx.sandbox.read_file(&path).await {
            Ok(content) => content,
            Err(e) => return Err(format!("Failed to read file '{}': {}", path, e)),
        };
        match contents.matches(find).count() {
            1 => {
                let contents = contents.replace(find, &replace);
                match ctx.sandbox.write_file(&path, &contents).await {
                    Ok(_) => Ok("success".to_string()),
                    Err(e) => Err(format!("Failed to write file '{}': {}", path, e)),
                }
            }
            num => Err(format!("Error: found {num} matches, expected 1")),
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
    type Context = SandboxCtx;

    fn name(&self) -> String {
        "done".to_string()
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
        ctx: &mut SandboxCtx,
        _args: &Self::Args,
    ) -> eyre::Result<Self::Output, Self::Error> {
        match self.validator.run(&mut ctx.sandbox).await {
            Ok(result) => match result {
                Ok(_) => Ok("success".to_string()),
                Err(err) => Err(format!("validation error: {}", err)),
            },
            Err(e) => Err(format!("validator failed: {}", e)),
        }
    }
}

pub trait Validator {
    fn run(
        &self,
        sandbox: &mut DaggerSandbox,
    ) -> impl Future<Output = Result<Result<(), String>>> + Send;

    fn boxed(self) -> Box<dyn ValidatorDyn>
    where
        Self: Sized + Send + Sync + 'static,
    {
        Box::new(self)
    }
}

pub trait ValidatorDyn: Send + Sync {
    fn run<'a>(
        &'a self,
        sandbox: &'a mut DaggerSandbox,
    ) -> Pin<Box<dyn Future<Output = Result<Result<(), String>>> + Send + 'a>>;
}

impl<T: Validator + Send + Sync + 'static> ValidatorDyn for T {
    fn run<'a>(
        &'a self,
        sandbox: &'a mut DaggerSandbox,
    ) -> Pin<Box<dyn Future<Output = Result<Result<(), String>>> + Send + 'a>> {
        Box::pin(self.run(sandbox))
    }
}

pub fn toolset<T: Validator + Send + Sync + 'static>(
    validator: T,
) -> Vec<Box<dyn crate::tool::ToolDyn<SandboxCtx>>> {
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
