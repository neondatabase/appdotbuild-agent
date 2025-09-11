use crate::agent::{Worker, ToolWorker};
use crate::thread;
use crate::toolbox::{self, basic::toolset};
use dabgent_mq::db::{EventStore, Metadata};
use dabgent_sandbox::SandboxDyn;
use eyre::Result;
use std::marker::PhantomData;

/// High-level combinator that orchestrates Worker + Sandbox
/// This is a reusable pattern for any agent that needs LLM + Sandbox execution
pub struct WorkerOrchestrator<S: EventStore, V: toolbox::Validator> {
    store: S,
    stream_id: String,
    aggregate_id: String,
    _validator: PhantomData<V>,
}

impl<S: EventStore, V: toolbox::Validator + Clone + Send + Sync + 'static> WorkerOrchestrator<S, V> {
    /// Create a new orchestrator for a specific stream/aggregate
    pub fn new(store: S, stream_id: String, aggregate_id: String) -> Self {
        Self {
            store,
            stream_id,
            aggregate_id,
            _validator: PhantomData,
        }
    }

    /// Setup and spawn the worker sandwich: LLM Worker + Sandbox Worker
    /// This is the core reusable pattern
    pub async fn spawn_workers(
        &self,
        llm: impl crate::llm::LLMClient + 'static,
        sandbox: Box<dyn SandboxDyn>,
        system_prompt: String,
        validator: V,
    ) -> Result<WorkerHandles> {
        tracing::info!(
            "Spawning worker sandwich for stream: {}, aggregate: {}",
            self.stream_id, self.aggregate_id
        );

        // Create tool set with the validator
        let llm_tools = toolset(validator.clone());
        let sandbox_tools = toolset(validator);

        // Create LLM worker
        let llm_worker = Worker::new(
            llm,
            self.store.clone(),
            system_prompt,
            llm_tools,
        );

        // Create Sandbox worker for tool execution
        let mut sandbox_worker = ToolWorker::new(
            sandbox,
            self.store.clone(),
            sandbox_tools,
        );

        // Spawn LLM worker
        let stream = self.stream_id.clone();
        let aggregate = self.aggregate_id.clone();
        let llm_handle = tokio::spawn(async move {
            tracing::info!("LLM worker started - stream: {}, aggregate: {}", stream, aggregate);
            match llm_worker.run(&stream, &aggregate).await {
                Ok(_) => tracing::info!("LLM worker completed successfully"),
                Err(e) => tracing::error!("LLM worker failed: {:?}", e),
            }
        });

        // Spawn Sandbox worker
        let stream = self.stream_id.clone();
        let aggregate = self.aggregate_id.clone();
        let sandbox_handle = tokio::spawn(async move {
            tracing::info!("Sandbox worker started - stream: {}, aggregate: {}", stream, aggregate);
            match sandbox_worker.run(&stream, &aggregate).await {
                Ok(_) => tracing::info!("Sandbox worker completed successfully"),
                Err(e) => tracing::error!("Sandbox worker failed: {:?}", e),
            }
        });

        Ok(WorkerHandles {
            llm_handle,
            sandbox_handle,
        })
    }

    /// Send a prompt to start processing
    pub async fn send_prompt(&self, prompt: String) -> Result<()> {
        tracing::info!("Sending prompt to workers: {}", prompt);
        
        self.store.push_event(
            &self.stream_id,
            &self.aggregate_id,
            &thread::Event::Prompted(prompt),
            &Metadata::default(),
        ).await?;
        
        Ok(())
    }

    /// Send a tool completion response
    pub async fn send_tool_response(&self, response: thread::ToolResponse) -> Result<()> {
        tracing::info!("Sending tool response to workers");
        
        self.store.push_event(
            &self.stream_id,
            &self.aggregate_id,
            &thread::Event::ToolCompleted(response),
            &Metadata::default(),
        ).await?;
        
        Ok(())
    }
}

/// Handles to the spawned worker tasks
pub struct WorkerHandles {
    pub llm_handle: tokio::task::JoinHandle<()>,
    pub sandbox_handle: tokio::task::JoinHandle<()>,
}

impl WorkerHandles {
    /// Wait for both workers to complete
    pub async fn wait(self) -> Result<()> {
        let (llm_result, sandbox_result) = tokio::join!(
            self.llm_handle,
            self.sandbox_handle
        );
        
        llm_result?;
        sandbox_result?;
        
        Ok(())
    }

    /// Abort both workers
    pub fn abort(self) {
        self.llm_handle.abort();
        self.sandbox_handle.abort();
    }
}

/// Builder pattern for creating orchestrators with different configurations
pub struct WorkerOrchestratorBuilder<S: EventStore> {
    store: S,
    stream_suffix: Option<String>,
    aggregate_suffix: Option<String>,
}

impl<S: EventStore> WorkerOrchestratorBuilder<S> {
    pub fn new(store: S) -> Self {
        Self {
            store,
            stream_suffix: None,
            aggregate_suffix: None,
        }
    }

    /// Add a suffix to the stream ID (e.g., "_planning", "_execution")
    pub fn with_stream_suffix(mut self, suffix: &str) -> Self {
        self.stream_suffix = Some(suffix.to_string());
        self
    }

    /// Add a suffix to the aggregate ID
    pub fn with_aggregate_suffix(mut self, suffix: &str) -> Self {
        self.aggregate_suffix = Some(suffix.to_string());
        self
    }

    /// Build the orchestrator
    pub fn build<V: toolbox::Validator + Clone + Send + Sync + 'static>(
        self,
        base_stream_id: String,
        base_aggregate_id: String,
    ) -> WorkerOrchestrator<S, V> {
        let stream_id = match self.stream_suffix {
            Some(suffix) => format!("{}{}", base_stream_id, suffix),
            None => base_stream_id,
        };
        
        let aggregate_id = match self.aggregate_suffix {
            Some(suffix) => format!("{}{}", base_aggregate_id, suffix),
            None => base_aggregate_id,
        };
        
        WorkerOrchestrator::new(self.store, stream_id, aggregate_id)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::validator::NoOpValidator;
    use dabgent_mq::db::sqlite::SqliteStore;

    #[tokio::test]
    async fn test_orchestrator_builder() {
        let pool = sqlx::SqlitePool::connect(":memory:").await.unwrap();
        let store = SqliteStore::new(pool);
        store.migrate().await;

        let orchestrator: WorkerOrchestrator<_, NoOpValidator> = WorkerOrchestratorBuilder::new(store)
            .with_stream_suffix("_planning")
            .with_aggregate_suffix("_thread")
            .build("test".to_string(), "demo".to_string());

        assert_eq!(orchestrator.stream_id, "test_planning");
        assert_eq!(orchestrator.aggregate_id, "demo_thread");
    }
}