use dabgent_mq::EventStore;
use eyre::Result;
use serde::{Deserialize, Serialize};
use super::{NoSandboxTool, NoSandboxAdapter};

/// Tool for creating a plan from task descriptions
pub struct CreatePlanTool<S: EventStore> {
    store: S,
    stream_id: String,
}

impl<S: EventStore + Clone> CreatePlanTool<S> {
    pub fn new(store: S, stream_id: String) -> Self {
        Self {
            store,
            stream_id,
        }
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CreatePlanArgs {
    pub tasks: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CreatePlanOutput {
    pub tasks: Vec<String>,
    pub message: String,
}

impl<S: EventStore + Clone + Send + Sync> NoSandboxTool for CreatePlanTool<S> {
    type Args = CreatePlanArgs;
    type Output = CreatePlanOutput;
    type Error = String;

    fn name(&self) -> String {
        "create_plan".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "Create a plan by breaking down a task into concrete, actionable steps.".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "description": "A concrete, actionable task description"
                        },
                        "description": "An ordered list of tasks to complete"
                    }
                },
                "required": ["tasks"]
            }),
        }
    }

    async fn call(
        &self,
        args: Self::Args,
    ) -> Result<Result<Self::Output, Self::Error>> {
        tracing::info!("CreatePlanTool called with {} tasks", args.tasks.len());

        // Create PlanCreated event
        let event = crate::event::Event::PlanCreated {
            tasks: args.tasks.clone(),
        };

        // Push event to store
        match self.store
            .push_event(&self.stream_id, "planner", &event, &Default::default())
            .await {
            Ok(_) => {
                tracing::info!("PlanCreated event pushed to store successfully");
            },
            Err(e) => return Ok(Err(e.to_string())),
        }

        let message = format!("Created plan with {} tasks", args.tasks.len());

        Ok(Ok(CreatePlanOutput {
            tasks: args.tasks,
            message
        }))
    }
}

/// Tool for updating an existing plan
pub struct UpdatePlanTool<S: EventStore> {
    store: S,
    stream_id: String,
}

impl<S: EventStore> UpdatePlanTool<S> {
    pub fn new(store: S, stream_id: String) -> Self {
        Self { store, stream_id }
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct UpdatePlanArgs {
    pub tasks: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct UpdatePlanOutput {
    pub tasks: Vec<String>,
    pub message: String,
}

impl<S: EventStore + Send + Sync> NoSandboxTool for UpdatePlanTool<S> {
    type Args = UpdatePlanArgs;
    type Output = UpdatePlanOutput;
    type Error = String;

    fn name(&self) -> String {
        "update_plan".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "Update the existing plan with a new set of tasks".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "description": "A concrete, actionable task description"
                        },
                        "description": "An updated ordered list of tasks to complete"
                    }
                },
                "required": ["tasks"]
            }),
        }
    }

    async fn call(
        &self,
        args: Self::Args,
    ) -> Result<Result<Self::Output, Self::Error>> {
        // Create PlanUpdated event
        let event = crate::event::Event::PlanUpdated {
            tasks: args.tasks.clone(),
        };

        // Push event to store
        match self.store
            .push_event(&self.stream_id, "planner", &event, &Default::default())
            .await {
            Ok(_) => {},
            Err(e) => return Ok(Err(e.to_string())),
        }

        let message = format!("Updated plan with {} tasks", args.tasks.len());

        Ok(Ok(UpdatePlanOutput {
            tasks: args.tasks,
            message
        }))
    }
}

pub struct AddTaskTool<S: EventStore> {
    store: S,
    stream_id: String,
}

impl<S: EventStore> AddTaskTool<S> {
    pub fn new(store: S, stream_id: String) -> Self {
        Self { store, stream_id }
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AddTaskArgs {
    pub task: String,
    pub position: Option<usize>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AddTaskOutput {
    pub tasks: Vec<String>,
    pub message: String,
}

impl<S: EventStore + Send + Sync> NoSandboxTool for AddTaskTool<S> {
    type Args = AddTaskArgs;
    type Output = AddTaskOutput;
    type Error = String;

    fn name(&self) -> String {
        "add_task".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "Add a single task to the existing plan".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "A concrete, actionable task description to add"
                    },
                    "position": {
                        "type": "integer",
                        "description": "Optional position to insert the task (0-based index). If not provided, adds to the end"
                    }
                },
                "required": ["task"]
            }),
        }
    }

    async fn call(
        &self,
        args: Self::Args,
    ) -> Result<Result<Self::Output, Self::Error>> {
        // Load current plan
        let query = dabgent_mq::Query::stream(&self.stream_id).aggregate("planner");
        let events = match self.store
            .load_events::<crate::event::Event>(&query, None)
            .await {
            Ok(events) => events,
            Err(e) => return Ok(Err(e.to_string())),
        };

        // Find the most recent plan
        let mut current_tasks: Option<Vec<String>> = None;
        for event in events.iter() {
            match event {
                crate::event::Event::PlanCreated { tasks } |
                crate::event::Event::PlanUpdated { tasks } => {
                    current_tasks = Some(tasks.clone());
                }
                _ => {}
            }
        }

        let mut tasks = match current_tasks {
            Some(tasks) => tasks,
            None => return Ok(Err("No plan exists yet. Use create_plan first.".to_string())),
        };

        // Add the new task at the specified position or at the end
        if let Some(pos) = args.position {
            if pos > tasks.len() {
                return Ok(Err(format!("Position {} is out of bounds (plan has {} tasks)", pos, tasks.len())));
            }
            tasks.insert(pos, args.task.clone());
        } else {
            tasks.push(args.task.clone());
        }

        // Create PlanUpdated event with the new task list
        let event = crate::event::Event::PlanUpdated {
            tasks: tasks.clone(),
        };

        // Push event to store
        match self.store
            .push_event(&self.stream_id, "planner", &event, &Default::default())
            .await {
            Ok(_) => {},
            Err(e) => return Ok(Err(e.to_string())),
        }

        let message = format!("Added task '{}' to plan", args.task);

        Ok(Ok(AddTaskOutput {
            tasks,
            message,
        }))
    }
}

pub struct CompleteTaskTool<S: EventStore> {
    store: S,
    stream_id: String,
}

impl<S: EventStore> CompleteTaskTool<S> {
    pub fn new(store: S, stream_id: String) -> Self {
        Self { store, stream_id }
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CompleteTaskArgs {
    pub task_index: usize,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CompleteTaskOutput {
    pub task: String,
    pub message: String,
}

impl<S: EventStore + Send + Sync> NoSandboxTool for CompleteTaskTool<S> {
    type Args = CompleteTaskArgs;
    type Output = CompleteTaskOutput;
    type Error = String;

    fn name(&self) -> String {
        "complete_task".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "Mark a specific task in the plan as completed".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "task_index": {
                        "type": "integer",
                        "description": "The index of the task to mark as completed (0-based)"
                    }
                },
                "required": ["task_index"]
            }),
        }
    }

    async fn call(
        &self,
        args: Self::Args,
    ) -> Result<Result<Self::Output, Self::Error>> {
        // Load current plan to validate task exists
        let query = dabgent_mq::Query::stream(&self.stream_id).aggregate("planner");
        let events = match self.store
            .load_events::<crate::event::Event>(&query, None)
            .await {
            Ok(events) => events,
            Err(e) => return Ok(Err(e.to_string())),
        };

        // Find the most recent plan
        let mut current_tasks: Option<Vec<String>> = None;
        for event in events.iter() {
            match event {
                crate::event::Event::PlanCreated { tasks } |
                crate::event::Event::PlanUpdated { tasks } => {
                    current_tasks = Some(tasks.clone());
                }
                _ => {}
            }
        }

        let tasks = match current_tasks {
            Some(tasks) => tasks,
            None => return Ok(Err("No plan exists yet. Use create_plan first.".to_string())),
        };

        // Validate task index
        if args.task_index >= tasks.len() {
            return Ok(Err(format!(
                "Task index {} is out of bounds (plan has {} tasks)",
                args.task_index,
                tasks.len()
            )));
        }

        let task = tasks[args.task_index].clone();

        // Create TaskCompleted event for the specific task
        let event = crate::event::Event::TaskCompleted {
            success: true,
            summary: "Planning task completed".to_string()
        };

        // Push event to store with the appropriate thread_id
        let thread_id = format!("task-{}", args.task_index);
        match self.store
            .push_event(&self.stream_id, &thread_id, &event, &Default::default())
            .await {
            Ok(_) => {},
            Err(e) => return Ok(Err(e.to_string())),
        }

        let message = format!("Marked task {} as completed: '{}'", args.task_index, task);

        Ok(Ok(CompleteTaskOutput {
            task,
            message,
        }))
    }
}

/// Tool for getting the current plan status from events
pub struct GetPlanStatusTool<S: EventStore> {
    store: S,
    stream_id: String,
}

impl<S: EventStore> GetPlanStatusTool<S> {
    pub fn new(store: S, stream_id: String) -> Self {
        Self { store, stream_id }
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct GetPlanStatusArgs {}

#[derive(Debug, Serialize, Deserialize)]
pub struct TaskStatus {
    pub description: String,
    pub thread_id: String,
    pub completed: bool,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct GetPlanStatusOutput {
    pub tasks: Vec<TaskStatus>,
    pub completed_count: usize,
    pub total_count: usize,
}

impl<S: EventStore + Send + Sync> NoSandboxTool for GetPlanStatusTool<S> {
    type Args = GetPlanStatusArgs;
    type Output = GetPlanStatusOutput;
    type Error = String;

    fn name(&self) -> String {
        "get_plan_status".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: self.name(),
            description: "Get the current status of the plan".to_string(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {},
                "required": []
            }),
        }
    }

    async fn call(
        &self,
        _args: Self::Args,
    ) -> Result<Result<Self::Output, Self::Error>> {
        // Load events to find the latest plan
        let query = dabgent_mq::Query::stream(&self.stream_id).aggregate("planner");
        let events = match self.store
            .load_events::<crate::event::Event>(&query, None)
            .await {
            Ok(events) => events,
            Err(e) => return Ok(Err(e.to_string())),
        };

        // Find the most recent plan
        let mut current_tasks: Option<Vec<String>> = None;
        for event in events.iter() {
            match event {
                crate::event::Event::PlanCreated { tasks } |
                crate::event::Event::PlanUpdated { tasks } => {
                    current_tasks = Some(tasks.clone());
                }
                _ => {}
            }
        }

        let tasks = match current_tasks {
            Some(tasks) => tasks,
            None => return Ok(Err("No plan exists yet. Use create_plan first.".to_string())),
        };

        // Convert to task status with thread IDs
        let task_statuses: Vec<TaskStatus> = tasks.iter()
            .enumerate()
            .map(|(i, desc)| TaskStatus {
                description: desc.clone(),
                thread_id: format!("task-{}", i),
                completed: false,  // Would need to track completion events
            })
            .collect();

        let total_count = task_statuses.len();
        let completed_count = task_statuses.iter().filter(|t| t.completed).count();

        Ok(Ok(GetPlanStatusOutput {
            tasks: task_statuses,
            completed_count,
            total_count,
        }))
    }
}

pub fn planning_toolset<S: EventStore + Clone + Send + Sync + 'static>(
    store: S,
    stream_id: String,
) -> Vec<Box<dyn super::ToolDyn>> {
    vec![
        Box::new(NoSandboxAdapter::new(CreatePlanTool::new(store.clone(), stream_id.clone()))),
        Box::new(NoSandboxAdapter::new(UpdatePlanTool::new(store.clone(), stream_id.clone()))),
        Box::new(NoSandboxAdapter::new(AddTaskTool::new(store.clone(), stream_id.clone()))),
        Box::new(NoSandboxAdapter::new(CompleteTaskTool::new(store.clone(), stream_id.clone()))),
        Box::new(NoSandboxAdapter::new(GetPlanStatusTool::new(store, stream_id))),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;
    use dabgent_mq::db::sqlite::SqliteStore;
    use sqlx::SqlitePool;

    async fn test_store() -> SqliteStore {
        let pool = SqlitePool::connect(":memory:")
            .await
            .expect("Failed to create in-memory SQLite pool");
        let store = SqliteStore::new(pool);
        store.migrate().await;
        store
    }

    #[tokio::test]
    async fn test_create_plan_tool() {
        let store = test_store().await;
        let tool = CreatePlanTool::new(store.clone(), "test-stream".to_string());

        // Test tool metadata
        assert_eq!(tool.name(), "create_plan");
        assert!(tool.definition().description.contains("Create a plan"));

        // Create a plan with structured tasks
        let args = CreatePlanArgs {
            tasks: vec!["Task 1".to_string(), "Task 2".to_string(), "Task 3".to_string()],
        };

        let result = tool.call(args).await.unwrap().unwrap();
        assert_eq!(result.tasks.len(), 3);
        assert_eq!(result.tasks[0], "Task 1");
        assert_eq!(result.tasks[1], "Task 2");
        assert_eq!(result.tasks[2], "Task 3");
        assert!(result.message.contains("3 tasks"));
    }

    #[tokio::test]
    async fn test_update_plan_tool() {
        let store = test_store().await;

        // First create a plan
        let create_tool = CreatePlanTool::new(store.clone(), "test-stream".to_string());
        let create_args = CreatePlanArgs {
            tasks: vec!["Initial task".to_string()],
        };
        create_tool.call(create_args).await.unwrap().unwrap();

        // Now test updating the plan
        let tool = UpdatePlanTool::new(store.clone(), "test-stream".to_string());
        assert_eq!(tool.name(), "update_plan");

        let args = UpdatePlanArgs {
            tasks: vec!["Updated task 1".to_string(), "Updated task 2".to_string()],
        };

        let result = tool.call(args).await.unwrap().unwrap();
        assert_eq!(result.tasks.len(), 2);
        assert_eq!(result.tasks[0], "Updated task 1");
        assert_eq!(result.tasks[1], "Updated task 2");
        assert!(result.message.contains("2 tasks"));
    }

    #[tokio::test]
    async fn test_get_plan_status_tool() {
        let store = test_store().await;

        // Create a plan first
        let create_tool = CreatePlanTool::new(store.clone(), "test-stream".to_string());
        let create_args = CreatePlanArgs {
            tasks: vec!["Task A".to_string(), "Task B".to_string(), "Task C".to_string()],
        };
        create_tool.call(create_args).await.unwrap().unwrap();

        // Get plan status
        let tool = GetPlanStatusTool::new(store.clone(), "test-stream".to_string());
        assert_eq!(tool.name(), "get_plan_status");

        let args = GetPlanStatusArgs {};
        let result = tool.call(args).await.unwrap().unwrap();

        assert_eq!(result.total_count, 3);
        assert_eq!(result.completed_count, 0); // No tasks completed yet
        assert_eq!(result.tasks.len(), 3);

        assert_eq!(result.tasks[0].description, "Task A");
        assert!(!result.tasks[0].completed);
        assert_eq!(result.tasks[0].thread_id, "task-0");

        assert_eq!(result.tasks[1].description, "Task B");
        assert!(!result.tasks[1].completed);
        assert_eq!(result.tasks[1].thread_id, "task-1");

        assert_eq!(result.tasks[2].description, "Task C");
        assert!(!result.tasks[2].completed);
        assert_eq!(result.tasks[2].thread_id, "task-2");
    }

    #[tokio::test]
    async fn test_get_plan_status_without_plan() {
        let store = test_store().await;
        let tool = GetPlanStatusTool::new(store, "test-stream".to_string());

        let args = GetPlanStatusArgs {};
        let result = tool.call(args).await.unwrap();

        assert!(result.is_err());
        if let Err(error) = result {
            assert!(error.contains("No plan exists"));
            assert!(error.contains("create_plan first"));
        }
    }

    #[tokio::test]
    async fn test_add_task_tool() {
        let store = test_store().await;

        // First create a plan
        let create_tool = CreatePlanTool::new(store.clone(), "test-stream".to_string());
        let create_args = CreatePlanArgs {
            tasks: vec!["Task 1".to_string(), "Task 3".to_string()],
        };
        create_tool.call(create_args).await.unwrap().unwrap();

        // Test adding a task at the end
        let tool = AddTaskTool::new(store.clone(), "test-stream".to_string());
        let args = AddTaskArgs {
            task: "Task 4".to_string(),
            position: None,
        };
        let result = tool.call(args).await.unwrap().unwrap();

        assert_eq!(result.tasks.len(), 3);
        assert_eq!(result.tasks[2], "Task 4");
        assert!(result.message.contains("Added task"));

        // Test adding a task at a specific position
        let args = AddTaskArgs {
            task: "Task 2".to_string(),
            position: Some(1),
        };
        let result = tool.call(args).await.unwrap().unwrap();

        assert_eq!(result.tasks.len(), 4);
        assert_eq!(result.tasks[1], "Task 2");
        assert_eq!(result.tasks[2], "Task 3");
    }

    #[tokio::test]
    async fn test_add_task_without_plan() {
        let store = test_store().await;
        let tool = AddTaskTool::new(store, "test-stream".to_string());

        let args = AddTaskArgs {
            task: "New task".to_string(),
            position: None,
        };
        let result = tool.call(args).await.unwrap();

        assert!(result.is_err());
        if let Err(error) = result {
            assert!(error.contains("No plan exists"));
        }
    }

    #[tokio::test]
    async fn test_complete_task_tool() {
        let store = test_store().await;

        // First create a plan
        let create_tool = CreatePlanTool::new(store.clone(), "test-stream".to_string());
        let create_args = CreatePlanArgs {
            tasks: vec![
                "Task 1".to_string(),
                "Task 2".to_string(),
                "Task 3".to_string(),
            ],
        };
        create_tool.call(create_args).await.unwrap().unwrap();

        // Mark task 1 (index 1) as completed
        let tool = CompleteTaskTool::new(store.clone(), "test-stream".to_string());
        let args = CompleteTaskArgs {
            task_index: 1,
        };
        let result = tool.call(args).await.unwrap().unwrap();

        assert_eq!(result.task, "Task 2");
        assert!(result.message.contains("Marked task 1 as completed"));

        // Verify TaskCompleted event was created
        let query = dabgent_mq::Query::stream("test-stream").aggregate("task-1");
        let events = store.load_events::<crate::event::Event>(&query, None).await.unwrap();

        let has_completed = events.iter().any(|e| matches!(e, crate::event::Event::TaskCompleted { success: true }));
        assert!(has_completed);
    }

    #[tokio::test]
    async fn test_complete_task_invalid_index() {
        let store = test_store().await;

        // Create a plan with 2 tasks
        let create_tool = CreatePlanTool::new(store.clone(), "test-stream".to_string());
        let create_args = CreatePlanArgs {
            tasks: vec!["Task 1".to_string(), "Task 2".to_string()],
        };
        create_tool.call(create_args).await.unwrap().unwrap();

        // Try to complete task at index 5 (out of bounds)
        let tool = CompleteTaskTool::new(store.clone(), "test-stream".to_string());
        let args = CompleteTaskArgs {
            task_index: 5,
        };
        let result = tool.call(args).await.unwrap();

        assert!(result.is_err());
        if let Err(error) = result {
            assert!(error.contains("out of bounds"));
            assert!(error.contains("plan has 2 tasks"));
        }
    }
}