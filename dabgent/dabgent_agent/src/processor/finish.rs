use super::agent::{Agent, AgentState, Command, Event};
use super::tools::TemplateConfig;
use crate::llm::FinishReason;
use crate::toolbox::ToolDyn;
use dabgent_mq::listener::EventHandler;
use dabgent_mq::{Envelope, EventStore, Handler};
use dabgent_sandbox::{DaggerSandbox, Sandbox, SandboxHandle, SandboxDyn};
use eyre::Result;
use rig::message::AssistantContent;
use std::path::Path;

pub trait ArtifactPreparer: Send + Sync {
    fn prepare(&self, sandbox: &mut Box<dyn SandboxDyn>) -> impl std::future::Future<Output = Result<()>> + Send;
}

pub struct FinishHandler {
    sandbox_handle: SandboxHandle,
    export_path: String,
    tools: Vec<Box<dyn ToolDyn>>,
    template_config: TemplateConfig,
}

impl FinishHandler {
    pub fn new(
        sandbox_handle: SandboxHandle,
        export_path: String,
        tools: Vec<Box<dyn ToolDyn>>,
        template_config: TemplateConfig,
    ) -> Self {
        Self {
            sandbox_handle,
            export_path,
            tools,
            template_config,
        }
    }

    async fn replay_and_export<A: Agent, ES: EventStore>(
        &mut self,
        handler: &Handler<AgentState<A>, ES>,
        aggregate_id: &str,
    ) -> Result<()> {
        let mut sandbox = match self.sandbox_handle.get(aggregate_id).await? {
            Some(s) => s,
            None => {
                self.sandbox_handle
                    .create_from_directory(
                        aggregate_id,
                        &self.template_config.host_dir,
                        &self.template_config.dockerfile,
                        vec![],
                    )
                    .await?
            }
        };

        let envelopes = handler.store().load_events::<AgentState<A>>(aggregate_id).await?;
        let events: Vec<Event<A::AgentEvent>> = envelopes.into_iter().map(|e| e.data).collect();

        self.replay_events(&mut sandbox, &events).await?;
        self.export_artifacts(&mut sandbox).await?;

        Ok(())
    }

    async fn replay_events<T>(&self, sandbox: &mut DaggerSandbox, events: &[Event<T>]) -> Result<()> {
        for event in events {
            if let Event::AgentCompletion { response } = event {
                if response.finish_reason == FinishReason::ToolUse {
                    self.replay_tool_calls(sandbox, response).await?;
                }
            }
        }
        Ok(())
    }

    async fn replay_tool_calls(&self, sandbox: &mut DaggerSandbox, response: &crate::llm::CompletionResponse) -> Result<()> {
        for content in response.choice.iter() {
            if let AssistantContent::ToolCall(call) = content {
                let tool_name = &call.function.name;
                let args = call.function.arguments.clone();

                if let Some(tool) = self.tools.iter().find(|t| t.name() == *tool_name) {
                    if tool.needs_replay() {
                        if let Err(e) = tool.call(args, sandbox).await {
                            tracing::warn!("Failed tool call during replay {}: {:?}", tool_name, e);
                        }
                    }
                }
            }
        }
        Ok(())
    }

    async fn export_artifacts(&mut self, sandbox: &mut DaggerSandbox) -> Result<String> {
        if let Some(parent) = Path::new(&self.export_path).parent() {
            std::fs::create_dir_all(parent)?;
        } else {
            std::fs::create_dir_all(&self.export_path)?;
        }

        let prep = Sandbox::exec(sandbox, "rm -rf /output && mkdir -p /output").await?;
        if prep.exit_code != 0 {
            eyre::bail!("Failed to prepare /output: {}", prep.stderr);
        }

        let git_commands = [
            "git -C /app init",
            "git -C /app config user.email agent@appbuild.com",
            "git -C /app config user.name Agent",
            "git -C /app add -A",
        ];

        for cmd in git_commands {
            let res = Sandbox::exec(sandbox, cmd).await?;
            if res.exit_code != 0 && !res.stderr.contains("already exists") && !res.stderr.is_empty() {
                eyre::bail!("Git command failed ({}): {}", cmd, res.stderr);
            }
        }

        let checkout = Sandbox::exec(sandbox, "git -C /app checkout-index --all --prefix=/output/ 2>&1")
            .await?;
        if checkout.exit_code != 0 {
            Sandbox::exec(sandbox, "cp -r /app/* /output/ 2>&1 || true").await?;
        }

        Sandbox::export_directory(sandbox, "/output", &self.export_path).await?;
        Ok(self.export_path.clone())
    }
}

impl<A: Agent, ES: EventStore> EventHandler<AgentState<A>, ES> for FinishHandler {
    async fn process(
        &mut self,
        handler: &Handler<AgentState<A>, ES>,
        envelope: &Envelope<AgentState<A>>,
    ) -> Result<()> {
        if let Event::Agent(_) = &envelope.data {
            use dabgent_mq::Event as MQEvent;
            let event_type = envelope.data.event_type();
            if event_type.contains("finished") || event_type.contains("done") {
                match self.replay_and_export(handler, &envelope.aggregate_id).await {
                    Ok(_) => {
                        tracing::info!("Export completed, triggering shutdown");
                        handler
                            .execute_with_metadata(
                                &envelope.aggregate_id,
                                Command::Shutdown,
                                envelope.metadata.clone(),
                            )
                            .await?;
                    }
                    Err(e) => {
                        tracing::error!("Failed to export artifacts: {}", e);
                    }
                }
            }
        }
        Ok(())
    }
}