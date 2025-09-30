use super::Processor;
use crate::event::Event;

use crate::toolbox::ToolDyn;
use dabgent_mq::{EventDb, EventStore, Query};
use dabgent_sandbox::SandboxDyn;
use eyre::Result;
use std::path::Path;
use crate::processor::replay::SandboxReplayer;

// trait for preparing artifacts before export
pub trait ArtifactPreparer: Send + Sync {
    fn prepare(&self, sandbox: &mut Box<dyn SandboxDyn>) -> impl std::future::Future<Output = Result<()>> + Send;
}

// default no-op implementation
#[derive(Default)]
pub struct NoOpPreparer;

impl ArtifactPreparer for NoOpPreparer {
    fn prepare(&self, _sandbox: &mut Box<dyn SandboxDyn>) -> impl std::future::Future<Output = Result<()>> + Send {
        async { Ok(()) }
    }
}

pub struct FinishProcessor<E: EventStore, P: ArtifactPreparer = NoOpPreparer> {
    sandbox: Box<dyn SandboxDyn>,
    event_store: E,
    export_path: String,
    tools: Vec<Box<dyn ToolDyn>>,
    preparer: P,
}



impl<E: EventStore> FinishProcessor<E, NoOpPreparer> {
    pub fn new(
        sandbox: Box<dyn SandboxDyn>,
        event_store: E,
        export_path: String,
        tools: Vec<Box<dyn ToolDyn>>,
    ) -> Self {
        Self {
            sandbox,
            event_store,
            export_path,
            tools,
            preparer: NoOpPreparer,
        }
    }
}

impl<E: EventStore, P: ArtifactPreparer> FinishProcessor<E, P> {
    pub fn new_with_preparer(
        sandbox: Box<dyn SandboxDyn>,
        event_store: E,
        export_path: String,
        tools: Vec<Box<dyn ToolDyn>>,
        preparer: P,
    ) -> Self {
        Self {
            sandbox,
            event_store,
            export_path,
            tools,
            preparer,
        }
    }

    async fn replay_tool_calls(&mut self, stream_id: &str, aggregate_id: &str) -> Result<()> {
        tracing::info!("Replaying tool calls to rebuild sandbox state");

        let query = Query::stream(stream_id).aggregate(aggregate_id);
        let events = self.event_store.load_events::<Event>(&query, None).await?;

        let mut replayer = SandboxReplayer::new(&mut self.sandbox, &self.tools);
        replayer.apply_all(&events).await?;

        tracing::info!("Tool call replay completed");
        Ok(())
    }



    async fn export_artifacts(&mut self) -> Result<String> {
        tracing::info!("Exporting artifacts (git-aware) from /app to {}", self.export_path);

        // Ensure export directory exists
        if let Some(parent) = Path::new(&self.export_path).parent() {
            std::fs::create_dir_all(parent)?;
        }

        // Deterministic git-based export: build /output inside sandbox, then export it
        // 1) Prepare output directory
        let prep = self.sandbox.exec("rm -rf /output && mkdir -p /output").await?;
        if prep.exit_code != 0 {
            eyre::bail!("Failed to prepare /output: {}", prep.stderr);
        }

        // 2) Initialize git and stage non-ignored files
        for cmd in [
            "git -C /app init",
            "git -C /app config user.email agent@appbuild.com",
            "git -C /app config user.name Agent",
            "git -C /app add -A",
        ] {
            let res = self.sandbox.exec(cmd).await?;
            if res.exit_code != 0 {
                eyre::bail!("Git command failed ({}): {}", cmd, res.stderr);
            }
        }

        // 3) Populate /output from the index (respects .gitignore)
        let checkout = self.sandbox.exec("git -C /app checkout-index --all --prefix=/output/").await?;
        if checkout.exit_code != 0 {
            eyre::bail!("git checkout-index failed: {}", checkout.stderr);
        }

        // 4) Export /output
        self.sandbox.export_directory("/output", &self.export_path).await?;

        tracing::info!("Artifacts exported successfully to {}", self.export_path);
        Ok(self.export_path.clone())
    }
}

impl<E: EventStore, P: ArtifactPreparer> Processor<Event> for FinishProcessor<E, P> {
    async fn run(&mut self, event: &EventDb<Event>) -> eyre::Result<()> {
        match &event.data {
            Event::TaskCompleted { success: true, .. } => {
                // Check event-sourced shutdown guard: if PipelineShutdown already exists, skip
                let query = Query::stream(&event.stream_id).aggregate(&event.aggregate_id);
                let prior_events = self.event_store.load_events::<Event>(&query, None).await?;
                if prior_events.iter().any(|e| matches!(e, Event::PipelineShutdown)) {
                    tracing::info!("PipelineShutdown already emitted; ignoring duplicate TaskCompleted");
                    return Ok(());
                }
                tracing::info!("Task completed successfully, starting artifact export");

                // Replay tool calls to rebuild complete sandbox state
                if let Err(e) = self.replay_tool_calls(&event.stream_id, &event.aggregate_id).await {
                    tracing::warn!("Failed to replay some tool calls: {}", e);
                }

                // Prepare artifacts (e.g., export requirements for FastAPI apps)
                self.preparer.prepare(&mut self.sandbox).await?;

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
            Event::TaskCompleted { success: false, .. } => {
                tracing::info!("Task completed with failure, allowing pipeline to continue for retry");
                // Don't shutdown - let the agent fix issues and retry
            }
            _ => {}
        }
        Ok(())
    }
}
