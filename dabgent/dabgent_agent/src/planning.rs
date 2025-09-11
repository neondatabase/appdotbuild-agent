use dabgent_mq::db::{EventStore, Metadata, Query};
use eyre::Result;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;

/// Events for planning and execution coordination
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum PlanningEvent {
    // Planning events
    TaskReceived { id: String, description: String },
    PlanCreated { id: String, plan: Plan },
    PlanUpdated { id: String, plan: Plan },
    
    // Execution events  
    ExecuteStep { id: String, step_index: usize, description: String },
    StepCompleted { id: String, step_index: usize, result: String },
    StepFailed { id: String, step_index: usize, error: String },
    
    // Coordination events
    RequestPlan { id: String },
    TaskCompleted { id: String },
}

impl dabgent_mq::Event for PlanningEvent {
    const EVENT_VERSION: &'static str = "1.0";
    fn event_type(&self) -> &'static str {
        match self {
            PlanningEvent::TaskReceived { .. } => "task_received",
            PlanningEvent::PlanCreated { .. } => "plan_created",
            PlanningEvent::PlanUpdated { .. } => "plan_updated",
            PlanningEvent::ExecuteStep { .. } => "execute_step",
            PlanningEvent::StepCompleted { .. } => "step_completed",
            PlanningEvent::StepFailed { .. } => "step_failed",
            PlanningEvent::RequestPlan { .. } => "request_plan",
            PlanningEvent::TaskCompleted { .. } => "task_completed",
        }
    }
}

/// A plan with steps that can be tracked
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Plan {
    pub task_id: String,
    pub description: String,
    pub steps: Vec<PlanStep>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlanStep {
    pub description: String,
    pub status: StepStatus,
    pub result: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum StepStatus {
    Pending,
    InProgress,
    Completed,
    Failed,
}

/// Planning agent that manages plans in memory and coordinates via events
pub struct PlanningAgent<S: EventStore> {
    store: S,
    stream_id: String,
    aggregate_id: String,
    plans: Arc<RwLock<HashMap<String, Plan>>>,
}

impl<S: EventStore> PlanningAgent<S> {
    pub fn new(store: S, stream_id: String, aggregate_id: String) -> Self {
        Self {
            store,
            stream_id,
            aggregate_id,
            plans: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Start the planning agent to listen for events
    pub async fn start(&self) -> Result<()> {
        let store = self.store.clone();
        let stream_id = self.stream_id.clone();
        let aggregate_id = self.aggregate_id.clone();
        let plans = self.plans.clone();
        
        tokio::spawn(async move {
            let mut receiver = store.subscribe::<PlanningEvent>(&Query {
                stream_id: stream_id.clone(),
                event_type: None,
                aggregate_id: Some(aggregate_id.clone()),
            }).unwrap();
            
            while let Some(Ok(event)) = receiver.next().await {
                match event {
                    PlanningEvent::TaskReceived { id, description } => {
                        tracing::info!("Planning agent received task {}: {}", id, description);
                        
                        // Create a plan based on the task description
                        let mut steps = vec![
                            PlanStep {
                                description: "Set up project structure".to_string(),
                                status: StepStatus::Pending,
                                result: None,
                            },
                        ];
                        
                        // Add specific steps based on task type
                        if description.to_lowercase().contains("web") || description.to_lowercase().contains("service") {
                            steps.push(PlanStep {
                                description: "Create main.py with web service implementation".to_string(),
                                status: StepStatus::Pending,
                                result: None,
                            });
                            steps.push(PlanStep {
                                description: "Add hello world endpoint".to_string(),
                                status: StepStatus::Pending,
                                result: None,
                            });
                        }
                        
                        steps.push(PlanStep {
                            description: "Test and validate implementation".to_string(),
                            status: StepStatus::Pending,
                            result: None,
                        });
                        
                        let plan = Plan {
                            task_id: id.clone(),
                            description: description.clone(),
                            steps,
                            created_at: chrono::Utc::now(),
                            updated_at: chrono::Utc::now(),
                        };
                        
                        // Store plan in memory
                        plans.write().await.insert(id.clone(), plan.clone());
                        
                        // Emit plan created event
                        store.push_event(
                            &stream_id,
                            &aggregate_id,
                            &PlanningEvent::PlanCreated { id: id.clone(), plan: plan.clone() },
                            &Metadata::default(),
                        ).await.unwrap();
                        
                        // Start execution of first step
                        if let Some(first_step) = plan.steps.first() {
                            store.push_event(
                                &stream_id,
                                &aggregate_id,
                                &PlanningEvent::ExecuteStep {
                                    id: id.clone(),
                                    step_index: 0,
                                    description: first_step.description.clone(),
                                },
                                &Metadata::default(),
                            ).await.unwrap();
                        }
                    }
                    
                    PlanningEvent::StepCompleted { id, step_index, result } => {
                        tracing::info!("Step {} completed for task {}: {}", step_index, id, result);
                        
                        // Update plan in memory
                        let mut plans_guard = plans.write().await;
                        if let Some(plan) = plans_guard.get_mut(&id) {
                            if let Some(step) = plan.steps.get_mut(step_index) {
                                step.status = StepStatus::Completed;
                                step.result = Some(result);
                            }
                            plan.updated_at = chrono::Utc::now();
                            
                            // Check if there are more steps
                            let next_index = step_index + 1;
                            if let Some(next_step) = plan.steps.get(next_index) {
                                // Start next step
                                store.push_event(
                                    &stream_id,
                                    &aggregate_id,
                                    &PlanningEvent::ExecuteStep {
                                        id: id.clone(),
                                        step_index: next_index,
                                        description: next_step.description.clone(),
                                    },
                                    &Metadata::default(),
                                ).await.unwrap();
                            } else {
                                // All steps completed
                                store.push_event(
                                    &stream_id,
                                    &aggregate_id,
                                    &PlanningEvent::TaskCompleted { id: id.clone() },
                                    &Metadata::default(),
                                ).await.unwrap();
                            }
                            
                            // Emit plan updated event
                            store.push_event(
                                &stream_id,
                                &aggregate_id,
                                &PlanningEvent::PlanUpdated { id: id.clone(), plan: plan.clone() },
                                &Metadata::default(),
                            ).await.unwrap();
                        }
                    }
                    
                    PlanningEvent::RequestPlan { id } => {
                        // Return current plan
                        let plans_guard = plans.read().await;
                        if let Some(plan) = plans_guard.get(&id) {
                            store.push_event(
                                &stream_id,
                                &aggregate_id,
                                &PlanningEvent::PlanUpdated { id: id.clone(), plan: plan.clone() },
                                &Metadata::default(),
                            ).await.unwrap();
                        }
                    }
                    
                    _ => {}
                }
            }
        });
        
        Ok(())
    }

    /// Submit a new task to the planner
    pub async fn submit_task(&self, task_id: String, description: String) -> Result<()> {
        self.store.push_event(
            &self.stream_id,
            &self.aggregate_id,
            &PlanningEvent::TaskReceived { id: task_id, description },
            &Metadata::default(),
        ).await?;
        Ok(())
    }
    
    /// Get current plan for a task
    pub async fn get_plan(&self, task_id: &str) -> Option<Plan> {
        self.plans.read().await.get(task_id).cloned()
    }
}

/// Execution agent that implements tasks based on events from the planner
pub struct ExecutionAgent<S: EventStore> {
    store: S,
    stream_id: String,
    aggregate_id: String,
}

impl<S: EventStore> ExecutionAgent<S> {
    pub fn new(store: S, stream_id: String, aggregate_id: String) -> Self {
        Self {
            store,
            stream_id,
            aggregate_id,
        }
    }

    /// Start the execution agent to listen for execution events
    pub async fn start(&self) -> Result<()> {
        let store = self.store.clone();
        let stream_id = self.stream_id.clone();
        let aggregate_id = self.aggregate_id.clone();
        
        tokio::spawn(async move {
            let mut receiver = store.subscribe::<PlanningEvent>(&Query {
                stream_id: stream_id.clone(),
                event_type: None,
                aggregate_id: Some(aggregate_id.clone()),
            }).unwrap();
            
            while let Some(Ok(event)) = receiver.next().await {
                match event {
                    PlanningEvent::ExecuteStep { id, step_index, description } => {
                        tracing::info!("Execution agent executing step {} for task {}: {}", 
                                     step_index, id, description);
                        
                        // Simulate execution (in real implementation, this would use WorkerOrchestrator)
                        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
                        
                        // Report completion
                        let result = format!("Completed: {}", description);
                        store.push_event(
                            &stream_id,
                            &aggregate_id,
                            &PlanningEvent::StepCompleted { 
                                id, 
                                step_index, 
                                result 
                            },
                            &Metadata::default(),
                        ).await.unwrap();
                    }
                    _ => {}
                }
            }
        });
        
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use dabgent_mq::db::sqlite::SqliteStore;

    #[tokio::test]
    async fn test_planning_agent_manages_plan_in_memory() {
        let pool = sqlx::SqlitePool::connect(":memory:").await.unwrap();
        let store = SqliteStore::new(pool);
        store.migrate().await;
        
        let agent = PlanningAgent::new(store.clone(), "test".to_string(), "test".to_string());
        
        // Start the agent
        agent.start().await.unwrap();
        
        // Give the spawned task time to start
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        
        // Submit a task
        agent.submit_task("task1".to_string(), "Create a web service".to_string()).await.unwrap();
        
        // Poll for the plan to be created (up to 2 seconds)
        let mut plan = None;
        for _ in 0..20 {
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
            plan = agent.get_plan("task1").await;
            if plan.is_some() {
                break;
            }
        }
        
        assert!(plan.is_some(), "Plan should have been created for task1");
        
        let plan = plan.unwrap();
        assert_eq!(plan.task_id, "task1");
        assert!(plan.steps.len() > 0);
        assert_eq!(plan.steps[0].status, StepStatus::Pending);
    }
}