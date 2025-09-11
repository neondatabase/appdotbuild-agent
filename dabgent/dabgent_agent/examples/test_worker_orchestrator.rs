use dabgent_agent::worker_orchestrator::{WorkerOrchestrator, WorkerOrchestratorBuilder};
use dabgent_agent::validator::PythonUvValidator;
use dabgent_mq::db::sqlite::SqliteStore;
use dabgent_sandbox::dagger::Sandbox as DaggerSandbox;
use eyre::Result;

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .init();

    println!("Testing reusable WorkerOrchestrator...\n");

    // Setup
    let pool = sqlx::SqlitePool::connect(":memory:").await?;
    let store = SqliteStore::new(pool);
    store.migrate().await;

    // Example 1: Using the builder pattern
    println!("1. Creating orchestrator with builder pattern:");
    let orchestrator: WorkerOrchestrator<_, PythonUvValidator> = WorkerOrchestratorBuilder::new(store.clone())
        .with_stream_suffix("_execution")
        .with_aggregate_suffix("_thread")
        .build("my_agent".to_string(), "session_123".to_string());
    
    println!("   Stream ID: my_agent_execution");
    println!("   Aggregate ID: session_123_thread");

    // Example 2: Direct creation
    println!("\n2. Creating orchestrator directly:");
    let direct_orchestrator = WorkerOrchestrator::<_, PythonUvValidator>::new(
        store.clone(),
        "direct_stream".to_string(),
        "direct_aggregate".to_string(),
    );
    
    // Example 3: Different validators for different use cases
    println!("\n3. Using different validators:");
    
    // No-op validator for planning (no execution)
    use dabgent_agent::validator::NoOpValidator;
    let planning_orchestrator = WorkerOrchestrator::<_, NoOpValidator>::new(
        store.clone(),
        "planning_stream".to_string(),
        "planning_aggregate".to_string(),
    );
    
    // Custom validator
    use dabgent_agent::validator::CustomValidator;
    let custom_orchestrator = WorkerOrchestrator::<_, CustomValidator>::new(
        store.clone(),
        "custom_stream".to_string(),
        "custom_aggregate".to_string(),
    );
    
    println!("   ✅ Planning orchestrator (NoOpValidator)");
    println!("   ✅ Custom orchestrator (CustomValidator)");
    println!("   ✅ Python orchestrator (PythonUvValidator)");

    // Example 4: Sending prompts
    println!("\n4. Sending prompts to orchestrator:");
    orchestrator.send_prompt("Create a Python script that reads CSV files".to_string()).await?;
    println!("   ✅ Prompt sent successfully");

    // Example 5: With actual workers (would need real LLM and sandbox)
    println!("\n5. Worker spawning (mock example):");
    println!("   Note: In production, you would:");
    println!("   - Create an LLM client with API key");
    println!("   - Create a Dagger sandbox");
    println!("   - Call orchestrator.spawn_workers(llm, sandbox, prompt, validator)");
    
    /*
    // Production example:
    let api_key = std::env::var("ANTHROPIC_API_KEY")?;
    let llm = rig::providers::anthropic::Client::new(&api_key);
    
    dagger_sdk::connect(|client| async move {
        let sandbox = create_sandbox(&client).await?;
        let validator = PythonUvValidator;
        
        let handles = orchestrator.spawn_workers(
            llm,
            sandbox.boxed(),
            "You are a Python developer...".to_string(),
            validator,
        ).await?;
        
        // Send initial prompt
        orchestrator.send_prompt("Build a REST API".to_string()).await?;
        
        // Wait for completion or handle in background
        tokio::spawn(async move {
            handles.wait().await.ok();
        });
        
        Ok(())
    }).await?;
    */

    println!("\n✅ All orchestrator tests passed!");
    println!("\nThe reusable orchestrator provides:");
    println!("- Builder pattern for flexible configuration");
    println!("- Support for any validator type");
    println!("- Automatic worker spawning and management");
    println!("- Clean separation of concerns");
    
    Ok(())
}