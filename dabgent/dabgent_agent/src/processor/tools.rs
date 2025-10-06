use super::agent::{Agent, AgentState, Command, Event};
use crate::toolbox::{ToolCallExt, ToolDyn};
use dabgent_mq::{Envelope, EventHandler, EventStore, Handler};
use dabgent_sandbox::{Sandbox, SandboxHandle};
use eyre::Result;
use rig::message::{ToolCall, ToolResult};

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

/// Dockerfile dir from the source workspace
pub fn get_dockerfile_dir_from_src_ws() -> String {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("examples")
        .to_str()
        .expect("project dir is a non-Unicode string")
        .to_owned()
}

pub struct ToolHandler {
    tools: Vec<Box<dyn ToolDyn>>,
    dagger: SandboxHandle,
    config: TemplateConfig,
}

impl ToolHandler {
    pub fn new(
        tools: Vec<Box<dyn ToolDyn>>,
        dagger: SandboxHandle,
        config: TemplateConfig,
    ) -> Self {
        Self {
            tools,
            dagger,
            config,
        }
    }

    async fn run_tools(&self, aggregate_id: &str, calls: &[ToolCall]) -> Result<Vec<ToolResult>> {
        let mut sandbox = match self.dagger.get(aggregate_id).await? {
            Some(sandbox) => {
                tracing::info!("Using existing sandbox for aggregate_id: {}", aggregate_id);
                sandbox
            }
            None => {
                tracing::info!(
                    "Creating new sandbox for aggregate_id: {} from directory: {}, dockerfile: {}",
                    aggregate_id,
                    self.config.host_dir,
                    self.config.dockerfile
                );
                let mut sandbox = self.dagger
                    .create_from_directory(
                        aggregate_id,
                        &self.config.host_dir,
                        &self.config.dockerfile,
                        vec![],
                    )
                    .await?;

                // Seed template if configured
                if let Some(template_path) = &self.config.template_path {
                    tracing::info!(
                        "Seeding template from: {} into base path: {}",
                        template_path,
                        self.config.template_base_path
                    );

                    let template_files = crate::sandbox_seed::collect_template_files(
                        std::path::Path::new(template_path),
                        &self.config.template_base_path
                    )?;

                    let hash = crate::sandbox_seed::compute_template_hash(&template_files.files);

                    // Write files directly to sandbox
                    for (path, content) in &template_files.files {
                        sandbox.write_file(path, content).await?;
                    }

                    tracing::info!(
                        "Template seeded successfully: {} files written, hash: {}",
                        template_files.files.len(),
                        hash
                    );
                }

                sandbox
            }
        };
        let mut results = Vec::new();
        for (call, tool) in calls.iter().filter_map(|call| self.match_tool(call)) {
            results.push(
                call.to_result(
                    tool.call(call.function.arguments.clone(), &mut sandbox)
                        .await?,
                ),
            );
        }
        self.dagger.set(aggregate_id, sandbox).await?;
        Ok(results)
    }

    fn match_tool<'a>(
        &'a self,
        call: &'a ToolCall,
    ) -> Option<(&'a ToolCall, &'a Box<dyn ToolDyn>)> {
        self.get_tool(&call.function.name).map(|tool| (call, tool))
    }

    fn get_tool(&self, name: &str) -> Option<&Box<dyn ToolDyn>> {
        self.tools.iter().find(|t| t.name() == name)
    }
}

impl<A: Agent, ES: EventStore> EventHandler<AgentState<A>, ES> for ToolHandler {
    async fn process(
        &mut self,
        handler: &Handler<AgentState<A>, ES>,
        event: &Envelope<AgentState<A>>,
    ) -> Result<()> {
        if let Event::ToolCalls { calls } = &event.data {
            let results = self.run_tools(&event.aggregate_id, &calls).await?;
            if !results.is_empty() {
                handler
                    .execute_with_metadata(
                        &event.aggregate_id,
                        Command::PutToolResults { results },
                        event.metadata.clone(),
                    )
                    .await?;
            }
        }
        Ok(())
    }
}
