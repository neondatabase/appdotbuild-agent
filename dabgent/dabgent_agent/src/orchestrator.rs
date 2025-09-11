use crate::worker_orchestrator::WorkerOrchestrator;
use crate::thread;
use dabgent_mq::db::{EventStore, Query};
use dabgent_sandbox::SandboxDyn;
use eyre::Result;
use std::future::Future;
use std::pin::Pin;

/// System prompt for the execution agent
/// This agent focuses on implementing Python solutions
const EXECUTION_PROMPT: &str = r#"
You are a Python software engineer.
Workspace is already set up using uv init.
Use uv package manager if you need to add extra libraries.
Program will be run using uv run main.py command.

Your task is to implement Python solutions.
Focus on creating working, well-structured code.
Test your implementation to ensure it works correctly.
"#;

/// Orchestrator that coordinates task execution
/// This is a thin layer that wires together the worker sandwich pattern
pub struct PlanningOrchestrator<S: EventStore> {
    store: S,
    stream_id: String,
    aggregate_id: String,
}

impl<S: EventStore> PlanningOrchestrator<S> {
    pub fn new(store: S, stream_id: String, aggregate_id: String) -> Self {
        Self {
            store,
            stream_id: format!("{}_planning", stream_id),
            aggregate_id,
        }
    }

    /// Setup workers using the WorkerOrchestrator pattern
    /// This creates the "sandwich" of LLM Worker + Sandbox Worker
    pub async fn setup_workers<V>(
        &self,
        sandbox: Box<dyn SandboxDyn>,
        llm: impl crate::llm::LLMClient + 'static,
        validator: V,
    ) -> Result<()>
    where
        V: crate::toolbox::Validator + Clone + Send + Sync + 'static,
    {
        tracing::info!("Setting up orchestrator with worker sandwich pattern");
        
        // Use WorkerOrchestrator to create the worker sandwich
        let orchestrator = WorkerOrchestrator::<S, V>::new(
            self.store.clone(),
            self.stream_id.clone(),
            self.aggregate_id.clone(),
        );

        // Spawn workers with execution-focused prompt
        let handles = orchestrator.spawn_workers(
            llm,
            sandbox,
            EXECUTION_PROMPT.to_string(),
            validator
        ).await?;
        
        // Workers run independently
        drop(handles);
        
        tracing::info!("✅ Orchestrator setup complete");
        Ok(())
    }

    /// Process a user message by sending it to the workers
    pub async fn process_message(&self, content: String) -> Result<()> {
        tracing::info!("Processing message: {}", content);
        
        // Send task directly to workers
        let orchestrator = WorkerOrchestrator::<S, crate::validator::NoOpValidator>::new(
            self.store.clone(),
            self.stream_id.clone(),
            self.aggregate_id.clone(),
        );
        
        orchestrator.send_prompt(content).await?;
        
        Ok(())
    }

    /// Monitor progress by subscribing to thread events
    pub async fn monitor_progress<F>(&self, mut on_status: F) -> Result<()>
    where
        F: FnMut(String) -> Pin<Box<dyn Future<Output = Result<()>> + Send>> + Send + 'static,
    {
        let mut receiver = self.store.subscribe::<thread::Event>(&Query {
            stream_id: self.stream_id.clone(),
            event_type: None,
            aggregate_id: Some(self.aggregate_id.clone()),
        })?;
        
        let timeout = std::time::Duration::from_secs(300);
        
        loop {
            match tokio::time::timeout(timeout, receiver.next()).await {
                Ok(Some(Ok(event))) => {
                    let status = self.format_event_status(&event);
                    on_status(status).await?;
                    
                    // Check if task is complete
                    if self.is_task_complete(&event) {
                        on_status("✅ Task completed successfully!".to_string()).await?;
                        break;
                    }
                }
                Ok(Some(Err(e))) => {
                    on_status(format!("❌ Error: {}", e)).await?;
                    break;
                }
                Ok(None) => {
                    on_status("⚠️ Event stream closed".to_string()).await?;
                    break;
                }
                Err(_) => {
                    on_status("⏱️ Task timed out after 5 minutes".to_string()).await?;
                    break;
                }
            }
        }
        
        Ok(())
    }

    fn format_event_status(&self, event: &thread::Event) -> String {
        match event {
            thread::Event::Prompted(task) => {
                let first_line = task.lines().next().unwrap_or(task);
                format!("🎯 Starting: {}", first_line)
            }
            thread::Event::LlmCompleted(_) => {
                "🤔 Processing...".to_string()
            }
            thread::Event::ToolCompleted(_) => {
                "🔧 Executing...".to_string()
            }
            thread::Event::UserResponded(response) => {
                format!("💬 User: {}", response.content)
            }
        }
    }

    fn is_task_complete(&self, event: &thread::Event) -> bool {
        // Simple heuristic - check if the tool response indicates completion
        match event {
            thread::Event::ToolCompleted(response) => {
                let response_str = format!("{:?}", response);
                response_str.contains("complete") || 
                response_str.contains("done") ||
                response_str.contains("successfully")
            }
            _ => false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use dabgent_mq::db::sqlite::SqliteStore;

    #[test]
    fn test_execution_prompt() {
        assert!(EXECUTION_PROMPT.contains("Python"));
        assert!(EXECUTION_PROMPT.contains("uv"));
        assert!(!EXECUTION_PROMPT.contains("plan.md")); // Should not mention planning
    }

    #[tokio::test]
    async fn test_orchestrator_creation() {
        let pool = sqlx::SqlitePool::connect(":memory:").await.unwrap();
        let store = SqliteStore::new(pool);
        store.migrate().await;
        
        let orchestrator = PlanningOrchestrator::new(
            store,
            "test".to_string(),
            "demo".to_string()
        );
        
        assert_eq!(orchestrator.stream_id, "test_planning");
        assert_eq!(orchestrator.aggregate_id, "demo");
    }
}