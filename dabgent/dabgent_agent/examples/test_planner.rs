use dabgent_agent::planner::{Planner, PlanUpdate};
use dabgent_mq::db::sqlite::SqliteStore;
use eyre::Result;

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .init();

    println!("Testing Planner functionality...\n");

    // Setup store
    let pool = sqlx::SqlitePool::connect(":memory:").await?;
    let store = SqliteStore::new(pool);
    store.migrate().await;

    // Create planner
    let planner = Planner::new(
        store.clone(),
        "test_planner".to_string(),
        "test_aggregate".to_string(),
    );

    // Test 1: Start planning
    println!("1. Starting planning for a task...");
    planner.start_planning("Build a REST API with authentication".to_string()).await?;
    
    // Check if plan.md was created
    if let Ok(content) = tokio::fs::read_to_string("plan.md").await {
        println!("   ✅ plan.md created:");
        println!("   {}", content.lines().take(5).collect::<Vec<_>>().join("\n   "));
    }

    // Test 2: Add steps
    println!("\n2. Adding steps to the plan...");
    planner.update_plan(PlanUpdate::AddStep("Design API endpoints".to_string())).await?;
    planner.update_plan(PlanUpdate::AddStep("Implement user model".to_string())).await?;
    planner.update_plan(PlanUpdate::AddStep("Add JWT authentication".to_string())).await?;

    // Test 3: Request clarification
    println!("\n3. Requesting clarification...");
    planner.update_plan(PlanUpdate::RequestClarification(
        "Which database should be used - PostgreSQL or MongoDB?".to_string()
    )).await?;

    // Test 4: Complete a step
    println!("\n4. Marking step as complete...");
    planner.update_plan(PlanUpdate::CompleteStep(0)).await?;

    // Test 5: Add notes
    println!("\n5. Adding notes...");
    planner.update_plan(PlanUpdate::AddNote(
        "Using JWT for stateless authentication".to_string()
    )).await?;

    // Test 6: Complete planning
    println!("\n6. Completing planning...");
    planner.complete_planning().await?;

    // Show final plan
    println!("\n=== Final Plan ===");
    if let Ok(content) = tokio::fs::read_to_string("plan.md").await {
        println!("{}", content);
    }

    // Clean up
    tokio::fs::remove_file("plan.md").await.ok();

    println!("\n✅ All planner tests passed!");
    Ok(())
}