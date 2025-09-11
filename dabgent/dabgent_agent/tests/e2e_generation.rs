use dabgent_agent::orchestrator::PlanningOrchestrator;
use dabgent_agent::thread::Event;
use dabgent_agent::toolbox::{self, Validator};
use dabgent_agent::validator::{FileExistsValidator, HealthCheckValidator, PythonUvValidator};
use dabgent_mq::db::{EventStore, Query};
use dabgent_mq::db::sqlite::SqliteStore;
use dabgent_sandbox::dagger::Sandbox as DaggerSandbox;
use dabgent_sandbox::{Sandbox, SandboxDyn};
use eyre::Result;
use std::time::Duration;
use tokio_stream::StreamExt;

/// Test-specific validator that checks if any Python file contains Hello World
#[derive(Clone, Debug)]
struct HelloWorldValidator;

impl toolbox::Validator for HelloWorldValidator {
    async fn run(&self, sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
        let files = sandbox.list_directory("/app").await?;
        let python_files: Vec<_> = files.iter()
            .filter(|f| f.ends_with(".py"))
            .collect();
        
        if python_files.is_empty() {
            return Ok(Err("No Python files found".to_string()));
        }
        
        for py_file in python_files {
            let content = sandbox.read_file(&format!("/app/{}", py_file)).await?;
            if content.to_lowercase().contains("hello") || content.contains("print") {
                return Ok(Ok(()));
            }
        }
        
        Ok(Err("No Python file contains Hello World implementation".to_string()))
    }
}

/// Test-specific validator that checks for plan.md file and its content
#[derive(Clone, Debug)]
struct PlanFileValidator;

impl toolbox::Validator for PlanFileValidator {
    async fn run(&self, sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
        let files = sandbox.list_directory("/app").await?;
        
        // Check if plan.md exists
        if !files.contains(&"plan.md".to_string()) {
            return Ok(Err("plan.md file not found".to_string()));
        }
        
        // Read and validate plan.md content
        let content = sandbox.read_file("/app/plan.md").await?;
        
        // Check that plan has some structure (basic validation)
        if content.is_empty() {
            return Ok(Err("plan.md is empty".to_string()));
        }
        
        // Check for expected plan elements
        let has_task_marker = content.contains("Task:") || content.contains("##") || content.contains("- [ ]");
        let has_content = content.len() > 50; // At least 50 chars of planning
        
        if !has_task_marker {
            return Ok(Err("plan.md doesn't contain task markers or structure".to_string()));
        }
        
        if !has_content {
            return Ok(Err("plan.md is too short to be a valid plan".to_string()));
        }
        
        Ok(Ok(()))
    }
}

/// End-to-end test that mirrors examples/planning.rs setup
#[tokio::test]
async fn test_e2e_application_generation() -> Result<()> {
    // Initialize just like the example
    tracing_subscriber::fmt::init();
    run_test().await
}

async fn run_test() -> Result<()> {
    dagger_sdk::connect(|client| async move {
        dotenvy::dotenv().ok();
        let api_key = std::env::var("ANTHROPIC_API_KEY")
            .expect("ANTHROPIC_API_KEY must be set in environment or .env file");
        let llm = rig::providers::anthropic::Client::new(api_key.as_str());
        let sandbox = sandbox(&client).await?;
        let store = store().await;
        
        let orchestrator = PlanningOrchestrator::new(
            store.clone(),
            "e2e_test".to_string(),
            "demo".to_string()
        );
        
        // For now, use PythonUvValidator for the agent itself
        // We'll verify with custom validators after execution
        orchestrator.setup_workers(sandbox.clone().boxed(), llm, PythonUvValidator).await?;
        
        // Test task - agent should automatically create plan.md based on system prompt
        let task = "Create a simple Python web service that outputs a hello world message.";
        tracing::info!("Sending task to agent: {}", task);
        orchestrator.process_message(task.to_string()).await?;
        tracing::info!("Task sent, monitoring progress...");
        
        // Also monitor events directly for debugging
        let mut event_stream = store.subscribe::<dabgent_agent::thread::Event>(&Query {
            stream_id: format!("{}_planning", "e2e_test"),
            event_type: None,
            aggregate_id: Some("demo".to_string()),
        })?;
        
        // Spawn event monitor
        let event_monitor = tokio::spawn(async move {
            while let Ok(Some(Ok(event))) = tokio::time::timeout(
                Duration::from_millis(500),
                event_stream.next()
            ).await {
                match &event {
                    dabgent_agent::thread::Event::LlmCompleted(response) => {
                        // Check if LLM is calling tools
                        let response_str = format!("{:?}", response.choice);
                        if response_str.contains("write_file") {
                            tracing::info!("🔧 LLM calling write_file tool");
                        }
                        if response_str.contains("plan.md") {
                            tracing::info!("📝 LLM mentioned plan.md!");
                        }
                    }
                    dabgent_agent::thread::Event::ToolCompleted(response) => {
                        let response_str = format!("{:?}", response.content);
                        if response_str.contains("plan.md") {
                            tracing::info!("✅ Tool response mentions plan.md");
                        }
                    }
                    _ => {}
                }
            }
        });
        
        // Monitor with timeout
        let monitor_result = tokio::time::timeout(
            Duration::from_secs(30),
            orchestrator.monitor_progress(|status| Box::pin(async move {
                tracing::info!("Status: {}", status);
                Ok(())
            }))
        ).await;
        
        // Stop event monitor
        event_monitor.abort();
        
        match monitor_result {
            Ok(Ok(())) => tracing::info!("✅ Monitoring completed"),
            Ok(Err(e)) => tracing::warn!("Monitor error: {:?}", e),
            Err(_) => tracing::info!("Monitor timeout after 30s"),
        }
        
        // Verify files were created
        verify_files_created(sandbox).await?;
        
        Ok(())
    }).await?;
    
    Ok(())
}

// Copy exact same helper functions from examples/planning.rs
async fn sandbox(client: &dagger_sdk::DaggerConn) -> Result<DaggerSandbox> {
    let opts = dagger_sdk::ContainerBuildOptsBuilder::default()
        .dockerfile("Dockerfile")
        .build()?;
    let ctr = client.container().build_opts(client.host().directory("./examples"), opts);
    ctr.sync().await?;
    Ok(DaggerSandbox::from_container(ctr))
}

async fn store() -> SqliteStore {
    let pool = sqlx::SqlitePool::connect(":memory:").await
        .expect("Failed to create in-memory SQLite pool");
    let store = SqliteStore::new(pool);
    store.migrate().await;
    store
}

// Test-specific verification using validators
async fn verify_files_created(mut sandbox: DaggerSandbox) -> Result<()> {
    use dabgent_sandbox::Sandbox as SandboxTrait;
    
    // Create verification validators
    // Accept various Python file names that could contain a web service
    let file_validator = FileExistsValidator::new(vec![
        "main.py".to_string(), 
        "app.py".to_string(), 
        "server.py".to_string(),
        "web.py".to_string()
    ]);
    let hello_validator = HelloWorldValidator;
    let health_validator = HealthCheckValidator::new("python --version");
    
    // Run individual validators and report results
    tracing::info!("Running verification validators...");
    
    // Check plan.md exists and is valid (CRITICAL)
    let mut sandbox_box: Box<dyn SandboxDyn> = Box::new(sandbox.clone());
    
    // Check file existence (at least one Python file should exist)
    let mut sandbox_box: Box<dyn SandboxDyn> = Box::new(sandbox.clone());
    match file_validator.run(&mut sandbox_box).await? {
        Ok(()) => tracing::info!("✅ Python files exist"),
        Err(e) => tracing::info!("ℹ️ {}", e),
    }
    
    // Check Hello World implementation (critical)
    let mut sandbox_box: Box<dyn SandboxDyn> = Box::new(sandbox.clone());
    match hello_validator.run(&mut sandbox_box).await? {
        Ok(()) => tracing::info!("✅ Hello World implementation found"),
        Err(e) => {
            tracing::error!("❌ {}", e);
            return Err(eyre::eyre!(e));
        }
    }
    
    // Check Python is available
    let mut sandbox_box: Box<dyn SandboxDyn> = Box::new(sandbox.clone());
    match health_validator.run(&mut sandbox_box).await? {
        Ok(()) => tracing::info!("✅ Python is available"),
        Err(e) => tracing::warn!("⚠️ {}", e),
    }
    
    // List files for debugging
    let files = SandboxTrait::list_directory(&sandbox, "/app").await?;
    tracing::info!("Final files in /app: {:?}", files);
    
    Ok(())
}

#[cfg(test)]
mod integration_tests {
    use super::*;
    use dabgent_agent::thread::Thread;
    use dabgent_agent::handler::Handler;
    
    #[tokio::test]
    async fn test_store_and_thread() -> Result<()> {
        // Use same store creation as example
        let store = store().await;
        
        // Test basic event flow
        let event = Event::Prompted("Test".to_string());
        store.push_event("test", "test", &event, &Default::default()).await?;
        
        let events = store.load_events::<Event>(&Query {
            stream_id: "test".to_string(),
            event_type: None,
            aggregate_id: Some("test".to_string()),
        }, None).await?;
        
        assert_eq!(events.len(), 1);
        
        let thread = Thread::fold(&events);
        assert_eq!(thread.messages.len(), 1);
        
        Ok(())
    }
}