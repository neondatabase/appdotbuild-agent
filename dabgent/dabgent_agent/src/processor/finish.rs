use super::Processor;
use crate::event::Event;
use crate::llm::{CompletionResponse, FinishReason};
use crate::toolbox::ToolDyn;
use dabgent_mq::{EventDb, EventStore, Query};
use dabgent_sandbox::SandboxDyn;
use eyre::Result;
use std::path::Path;

pub struct FinishProcessor<E: EventStore> {
    sandbox: Box<dyn SandboxDyn>,
    event_store: E,
    export_path: String,
    cleanup_patterns: Vec<String>,
    tools: Vec<Box<dyn ToolDyn>>,
}

impl<E: EventStore> FinishProcessor<E> {
    pub fn new(
        sandbox: Box<dyn SandboxDyn>,
        event_store: E,
        export_path: String,
        tools: Vec<Box<dyn ToolDyn>>,
    ) -> Self {
        let cleanup_patterns = vec![
            "node_modules".to_string(),
            ".venv".to_string(),
            "__pycache__".to_string(),
            ".git".to_string(),
            "target".to_string(),
            "dist".to_string(),
            "build".to_string(),
            ".next".to_string(),
            ".nuxt".to_string(),
            "coverage".to_string(),
            ".pytest_cache".to_string(),
            ".mypy_cache".to_string(),
            "*.pyc".to_string(),
            "*.pyo".to_string(),
            "*.log".to_string(),
            ".DS_Store".to_string(),
            "Thumbs.db".to_string(),
        ];

        Self {
            sandbox,
            event_store,
            export_path,
            cleanup_patterns,
            tools,
        }
    }

    pub fn with_cleanup_patterns(mut self, patterns: Vec<String>) -> Self {
        self.cleanup_patterns = patterns;
        self
    }

    async fn cleanup_temp_files(&mut self) -> Result<()> {
        tracing::info!("Cleaning up temporary files before export");

        for pattern in &self.cleanup_patterns {
            // Use find and rm to remove files/directories matching patterns
            let find_cmd = if pattern.contains('*') {
                format!("find /app -name '{}' -type f -delete", pattern)
            } else {
                format!("find /app -name '{}' -type d -exec rm -rf {{}} + 2>/dev/null || true", pattern)
            };

            match self.sandbox.exec(&find_cmd).await {
                Ok(result) => {
                    if result.exit_code != 0 && !result.stderr.is_empty() {
                        tracing::debug!("Cleanup command failed (non-critical): {}", result.stderr);
                    }
                }
                Err(e) => {
                    tracing::debug!("Cleanup command error (non-critical): {}", e);
                }
            }
        }

        Ok(())
    }

    async fn replay_tool_calls(&mut self, stream_id: &str, aggregate_id: &str) -> Result<()> {
        tracing::info!("Replaying tool calls to rebuild sandbox state");

        let query = Query::stream(stream_id).aggregate(aggregate_id);
        let events = self.event_store.load_events::<Event>(&query, None).await?;

        for event in events {
            if let Event::AgentMessage { response, .. } = &event {
                if response.finish_reason == FinishReason::ToolUse {
                    tracing::debug!("Replaying tool calls from agent message");
                    self.execute_tool_calls(response).await?;
                }
            }
        }

        tracing::info!("Tool call replay completed");
        Ok(())
    }

    async fn execute_tool_calls(&mut self, response: &CompletionResponse) -> Result<()> {

        for content in response.choice.iter() {
            if let rig::message::AssistantContent::ToolCall(call) = content {
                let tool = self.tools.iter().find(|t| t.name() == call.function.name);
                if let Some(tool) = tool {
                    let args = call.function.arguments.clone();
                    match tool.call(args, &mut self.sandbox).await {
                        Ok(_) => {
                            tracing::debug!("Successfully replayed tool call: {}", call.function.name);
                        }
                        Err(e) => {
                            tracing::warn!("Failed to replay tool call {}: {:?}", call.function.name, e);
                        }
                    }
                }
            }
        }
        Ok(())
    }

    async fn export_artifacts(&self) -> Result<String> {
        tracing::info!("Exporting artifacts from /app to {}", self.export_path);

        // Ensure export directory exists
        if let Some(parent) = Path::new(&self.export_path).parent() {
            std::fs::create_dir_all(parent)?;
        }

        // Export the /app directory
        self.sandbox.export_directory("/app", &self.export_path).await?;

        tracing::info!("Artifacts exported successfully to {}", self.export_path);
        Ok(self.export_path.clone())
    }
}

impl<E: EventStore> Processor<Event> for FinishProcessor<E> {
    async fn run(&mut self, event: &EventDb<Event>) -> eyre::Result<()> {
        match &event.data {
            Event::TaskCompleted { success: true } => {
                tracing::info!("Task completed successfully, starting artifact export");

                // Replay tool calls to rebuild complete sandbox state
                if let Err(e) = self.replay_tool_calls(&event.stream_id, &event.aggregate_id).await {
                    tracing::warn!("Failed to replay some tool calls: {}", e);
                }

                // First cleanup temporary files
                if let Err(e) = self.cleanup_temp_files().await {
                    tracing::warn!("Failed to cleanup some temporary files: {}", e);
                }

                // Export artifacts
                match self.export_artifacts().await {
                    Ok(export_path) => {
                        tracing::info!("Artifacts exported to: {}", export_path);

                        // Emit shutdown event to trigger pipeline termination
                        let shutdown_event = Event::PipelineShutdown;
                        self.event_store
                            .push_event(
                                &event.stream_id,
                                &event.aggregate_id,
                                &shutdown_event,
                                &Default::default(),
                            )
                            .await?;

                        tracing::info!("Pipeline shutdown event emitted");
                    }
                    Err(e) => {
                        tracing::error!("Failed to export artifacts: {}", e);
                        // Still emit shutdown on failure
                        let shutdown_event = Event::PipelineShutdown;
                        self.event_store
                            .push_event(
                                &event.stream_id,
                                &event.aggregate_id,
                                &shutdown_event,
                                &Default::default(),
                            )
                            .await?;
                    }
                }
            }
            Event::TaskCompleted { success: false } => {
                tracing::warn!("Task completed with failure, skipping export and shutting down");
                let shutdown_event = Event::PipelineShutdown;
                self.event_store
                    .push_event(
                        &event.stream_id,
                        &event.aggregate_id,
                        &shutdown_event,
                        &Default::default(),
                    )
                    .await?;
            }
            _ => {}
        }
        Ok(())
    }
}