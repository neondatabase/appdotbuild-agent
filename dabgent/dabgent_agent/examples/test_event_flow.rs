use dabgent_agent::orchestrator::PlanningOrchestrator;
use dabgent_agent::validator::PythonUvValidator;
use dabgent_mq::db::sqlite::SqliteStore;
use dabgent_mq::db::{EventStore, Query};
use dabgent_agent::thread;
use dabgent_sandbox::dagger::Sandbox as DaggerSandbox;
use dabgent_sandbox::Sandbox;
use eyre::Result;

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::DEBUG)
        .init();
    
    println!("Testing event flow...\n");
    
    // Setup store
    let pool = sqlx::SqlitePool::connect(":memory:").await?;
    let store = SqliteStore::new(pool);
    store.migrate().await;
    
    // Create orchestrator
    let stream_id = "test_stream".to_string();
    let aggregate_id = "test_aggregate".to_string();
    
    println!("Creating orchestrator with:");
    println!("  stream_id: {}", stream_id);
    println!("  aggregate_id: {}", aggregate_id);
    
    let orchestrator = PlanningOrchestrator::new(
        store.clone(),
        stream_id.clone(),
        aggregate_id.clone()
    );
    
    // The orchestrator will use stream_id + "_planning"
    let actual_stream = format!("{}_planning", stream_id);
    println!("  actual stream (with suffix): {}", actual_stream);
    
    // Check if we can push and retrieve events
    println!("\n1. Testing direct event push...");
    orchestrator.process_message("Test task".to_string()).await?;
    
    // Check if event was stored
    let events = store.load_events::<thread::Event>(&Query {
        stream_id: actual_stream.clone(),
        event_type: None,
        aggregate_id: Some(aggregate_id.clone()),
    }, None).await?;
    
    println!("   Events in store: {}", events.len());
    for (i, event) in events.iter().enumerate() {
        println!("   Event {}: {:?}", i, match event {
            thread::Event::Prompted(msg) => format!("Prompted: {}", &msg[..50.min(msg.len())]),
            thread::Event::LlmCompleted(_) => "LlmCompleted".to_string(),
            thread::Event::ToolCompleted(_) => "ToolCompleted".to_string(),
            thread::Event::UserResponded(_) => "UserResponded".to_string(),
        });
    }
    
    // Now test with workers (without actually running Dagger)
    println!("\n2. Testing with mock setup...");
    
    // Create a simple mock LLM (this will fail but we just want to see if workers start)
    let api_key = "test_key";
    let llm = rig::providers::anthropic::Client::new(api_key);
    
    println!("   Note: Workers will fail without real sandbox/LLM, but we can see if they start");
    
    // Try to subscribe to events
    println!("\n3. Testing event subscription...");
    let mut receiver = store.subscribe::<thread::Event>(&Query {
        stream_id: actual_stream.clone(),
        event_type: None,
        aggregate_id: Some(aggregate_id.clone()),
    })?;
    
    // Push another event
    orchestrator.process_message("Another test".to_string()).await?;
    
    // Try to receive it
    match tokio::time::timeout(std::time::Duration::from_secs(1), receiver.next()).await {
        Ok(Some(Ok(event))) => {
            println!("   Received event via subscription: {:?}", match &event {
                thread::Event::Prompted(msg) => format!("Prompted: {}", &msg[..50.min(msg.len())]),
                _ => "Other".to_string(),
            });
        }
        Ok(Some(Err(e))) => println!("   Subscription error: {}", e),
        Ok(None) => println!("   Subscription closed"),
        Err(_) => println!("   Timeout waiting for event"),
    }
    
    println!("\n✅ Event flow test completed");
    Ok(())
}