use dabgent_mq::db::{EventStore, Metadata, Query};
use eyre::Result;
use serde::{Deserialize, Serialize};
use std::future::Future;
use std::pin::Pin;

/// Planner that focuses solely on creating and managing plans
/// Validation and execution are handled by separate components
pub struct Planner<S: EventStore> {
    store: S,
    stream_id: String,
    aggregate_id: String,
}

impl<S: EventStore> Planner<S> {
    pub fn new(store: S, stream_id: String, aggregate_id: String) -> Self {
        Self {
            store,
            stream_id,
            aggregate_id,
        }
    }

    /// Start planning for a task
    pub async fn start_planning(&self, task: String) -> Result<()> {
        tracing::info!("Planner starting task: {}", task);
        
        // Create initial plan template
        let plan_content = format!(
            r#"# Task Planning

## Task Description
{}

## Plan
1. [ ] Analyze requirements
2. [ ] Break down into subtasks
3. [ ] Implement solution
4. [ ] Test and validate

## Notes
- Planning in progress...
"#,
            task
        );
        
        // Write initial plan to plan.md
        tokio::fs::write("plan.md", plan_content).await?;
        
        // Emit planning started event
        self.store.push_event(
            &self.stream_id,
            &self.aggregate_id,
            &PlannerEvent::PlanningStarted { task },
            &Metadata::default(),
        ).await?;
        
        Ok(())
    }

    /// Update the plan with new information
    pub async fn update_plan(&self, updates: PlanUpdate) -> Result<()> {
        tracing::info!("Updating plan: {:?}", updates);
        
        // Read current plan
        let mut plan_content = tokio::fs::read_to_string("plan.md").await
            .unwrap_or_else(|_| String::from("# Task Planning\n\n"));
        
        // Apply updates based on type
        match updates {
            PlanUpdate::AddStep(step) => {
                plan_content.push_str(&format!("\n- [ ] {}", step));
            }
            PlanUpdate::CompleteStep(index) => {
                // Mark step as complete
                let lines: Vec<String> = plan_content.lines()
                    .enumerate()
                    .map(|(i, line)| {
                        if line.starts_with("- [ ]") && i == index {
                            line.replace("- [ ]", "- [x]")
                        } else {
                            line.to_string()
                        }
                    })
                    .collect();
                plan_content = lines.join("\n");
            }
            PlanUpdate::AddNote(note) => {
                plan_content.push_str(&format!("\n\n## Note\n{}", note));
            }
            PlanUpdate::RequestClarification(question) => {
                plan_content.push_str(&format!("\n\n## ❓ Clarification Needed\n{}", question));
                
                // Emit clarification request event
                self.store.push_event(
                    &self.stream_id,
                    &self.aggregate_id,
                    &PlannerEvent::ClarificationRequested { question },
                    &Metadata::default(),
                ).await?;
            }
        }
        
        // Write updated plan
        tokio::fs::write("plan.md", plan_content).await?;
        
        // Emit plan updated event
        self.store.push_event(
            &self.stream_id,
            &self.aggregate_id,
            &PlannerEvent::PlanUpdated,
            &Metadata::default(),
        ).await?;
        
        Ok(())
    }

    /// Monitor planning progress
    pub async fn monitor<F>(&self, mut on_event: F) -> Result<()>
    where
        F: FnMut(PlannerEvent) -> Pin<Box<dyn Future<Output = Result<()>> + Send>> + Send + 'static,
    {
        let mut receiver = self.store.subscribe::<PlannerEvent>(&Query {
            stream_id: self.stream_id.clone(),
            event_type: None,
            aggregate_id: Some(self.aggregate_id.clone()),
        })?;
        
        while let Some(Ok(event)) = receiver.next().await {
            tracing::info!("Planner event: {:?}", event);
            
            // Check if planning is complete
            let is_complete = matches!(event, PlannerEvent::PlanningCompleted);
            
            on_event(event).await?;
            
            if is_complete {
                break;
            }
        }
        
        Ok(())
    }

    /// Mark planning as complete
    pub async fn complete_planning(&self) -> Result<()> {
        tracing::info!("Planning completed");
        
        // Update plan with completion status
        let mut plan_content = tokio::fs::read_to_string("plan.md").await?;
        plan_content.push_str("\n\n## ✅ Planning Complete\n");
        tokio::fs::write("plan.md", plan_content).await?;
        
        // Emit completion event
        self.store.push_event(
            &self.stream_id,
            &self.aggregate_id,
            &PlannerEvent::PlanningCompleted,
            &Metadata::default(),
        ).await?;
        
        Ok(())
    }
}

/// Events emitted by the planner
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum PlannerEvent {
    PlanningStarted { task: String },
    PlanUpdated,
    ClarificationRequested { question: String },
    ClarificationReceived { answer: String },
    PlanningCompleted,
}

impl dabgent_mq::Event for PlannerEvent {
    const EVENT_VERSION: &'static str = "1.0";

    fn event_type(&self) -> &'static str {
        match self {
            PlannerEvent::PlanningStarted { .. } => "planning_started",
            PlannerEvent::PlanUpdated => "plan_updated",
            PlannerEvent::ClarificationRequested { .. } => "clarification_requested",
            PlannerEvent::ClarificationReceived { .. } => "clarification_received",
            PlannerEvent::PlanningCompleted => "planning_completed",
        }
    }
}

/// Types of plan updates
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum PlanUpdate {
    AddStep(String),
    CompleteStep(usize),
    AddNote(String),
    RequestClarification(String),
}

/// System prompt for planning agent
pub const PLANNER_SYSTEM_PROMPT: &str = r#"
You are a planning specialist. Your role is to:
1. Analyze tasks and create detailed plans
2. Break down complex tasks into manageable steps
3. Update plan.md file with your planning progress
4. Request clarification when needed
5. Focus ONLY on planning, not implementation

Use markdown format in plan.md:
- [ ] for pending tasks
- [x] for completed tasks
- Clear headings and sections
- Notes for important decisions

You do NOT execute tasks, only plan them.
"#;