use super::agent::{Agent, AgentState, Command, Event};
use crate::toolbox::{ToolCallExt, ToolDyn};
use dabgent_mq::{Envelope, EventHandler, EventStore, Handler};
use dabgent_sandbox::SandboxHandle;
use eyre::Result;
use rig::message::{ToolCall, ToolResult};

pub struct TemplateConfig {
    pub host_dir: String,
    pub dockerfile: String,
}

impl TemplateConfig {
    pub fn new(host_dir: String, dockerfile: String) -> Self {
        Self {
            host_dir,
            dockerfile,
        }
    }

    pub fn default_dir<T: AsRef<str>>(host_dir: T) -> Self {
        Self {
            host_dir: host_dir.as_ref().to_string(),
            dockerfile: "Dockerfile".to_string(),
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
            Some(sandbox) => sandbox,
            None => {
                self.dagger
                    .create_from_directory(
                        aggregate_id,
                        &self.config.host_dir,
                        &self.config.dockerfile,
                    )
                    .await?
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
