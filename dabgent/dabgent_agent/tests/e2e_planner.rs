mod common;

use common::{create_test_store, PythonValidator};
use dabgent_agent::llm::{LLMClientDyn, WithRetryExt};
use dabgent_agent::processor::agent::{
    Agent, AgentState, Command, Event, Request, Response, Runtime,
};
use dabgent_agent::processor::link::{Link, link_runtimes};
use dabgent_agent::processor::llm::{LLMConfig, LLMHandler};
use dabgent_agent::processor::tools::{
    get_dockerfile_dir_from_src_ws, TemplateConfig, ToolHandler,
};
use dabgent_agent::toolbox::{basic::toolset, ToolCallExt};
use dabgent_mq::{Event as MQEvent, EventStore, Handler};
use dabgent_sandbox::SandboxHandle;
use eyre::Result;
use rig::client::ProviderClient;
use rig::completion::ToolDefinition;
use rig::message::{ToolCall, ToolResult, ToolResultContent, UserContent};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::Duration;
use tokio::time::timeout;

// Planner Agent
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct PlannerAgent;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum PlannerEvent {}

impl MQEvent for PlannerEvent {
    fn event_type(&self) -> String {
        "planner".to_string()
    }

    fn event_version(&self) -> String {
        "1.0".to_string()
    }
}

#[derive(Debug, thiserror::Error)]
pub enum PlannerError {}

impl Agent for PlannerAgent {
    const TYPE: &'static str = "e2e_planner";
    type AgentCommand = ();
    type AgentEvent = PlannerEvent;
    type AgentError = PlannerError;
    type Services = ();

    async fn handle_tool_results(
        state: &AgentState<Self>,
        _: &Self::Services,
        incoming: Vec<ToolResult>,
    ) -> Result<Vec<Event<Self::AgentEvent>>, Self::AgentError> {
        let completed = state.merge_tool_results(incoming);
        let content = completed.into_iter().map(UserContent::ToolResult);
        let content = rig::OneOrMany::many(content).unwrap();
        Ok(vec![Event::Request(Request::Completion { content })])
    }

    fn apply_event(_state: &mut AgentState<Self>, _event: Event<Self::AgentEvent>) {}
}

// Worker Agent
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct WorkerAgent {
    pub parent_id: Option<String>,
    pub parent_call: Option<ToolCall>,
    pub done_call_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum WorkerEvent {
    Grabbed {
        parent_id: String,
        call: ToolCall,
    },
    Finished {
        parent_id: String,
        call: ToolCall,
        result: String,
    },
}

impl MQEvent for WorkerEvent {
    fn event_type(&self) -> String {
        match self {
            WorkerEvent::Grabbed { .. } => "grabbed".to_string(),
            WorkerEvent::Finished { .. } => "finished".to_string(),
        }
    }

    fn event_version(&self) -> String {
        "1.0".to_string()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum WorkerCommand {
    Grab { parent_id: String, call: ToolCall },
}

#[derive(Debug, thiserror::Error)]
pub enum WorkerError {}

impl Agent for WorkerAgent {
    const TYPE: &'static str = "e2e_worker";
    type AgentCommand = WorkerCommand;
    type AgentEvent = WorkerEvent;
    type AgentError = WorkerError;
    type Services = ();

    async fn handle_tool_results(
        state: &AgentState<Self>,
        _: &Self::Services,
        incoming: Vec<ToolResult>,
    ) -> Result<Vec<Event<Self::AgentEvent>>, Self::AgentError> {
        let completed = state.merge_tool_results(incoming);
        if let Some(done_id) = &state.agent.done_call_id {
            if let Some(result) = completed.iter().find(|r| done_id == &r.id) {
                let is_done = result.content.iter().any(|c| match c {
                    ToolResultContent::Text(text) => text.text.contains("success"),
                    _ => false,
                });
                if is_done {
                    return Ok(vec![Event::Agent(WorkerEvent::Finished {
                        parent_id: state.agent.parent_id.clone().unwrap(),
                        call: state.agent.parent_call.clone().unwrap(),
                        result: "task completed".to_string(),
                    })]);
                }
            }
        }

        let content = completed.into_iter().map(UserContent::ToolResult);
        let content = rig::OneOrMany::many(content).unwrap();
        Ok(vec![Event::Request(Request::Completion { content })])
    }

    async fn handle_command(
        _state: &AgentState<Self>,
        cmd: Self::AgentCommand,
        _: &Self::Services,
    ) -> Result<Vec<Event<Self::AgentEvent>>, Self::AgentError> {
        match cmd {
            WorkerCommand::Grab { parent_id, call } => {
                let description = call
                    .function
                    .arguments
                    .get("description")
                    .unwrap()
                    .to_string();
                let content = rig::OneOrMany::one(UserContent::text(description));
                Ok(vec![
                    Event::Agent(WorkerEvent::Grabbed {
                        parent_id: parent_id.clone(),
                        call: call.clone(),
                    }),
                    Event::Request(Request::Completion { content }),
                ])
            }
        }
    }

    fn apply_event(state: &mut AgentState<Self>, event: Event<Self::AgentEvent>) {
        match event {
            Event::Request(Request::ToolCalls { ref calls }) => {
                for call in calls {
                    if call.function.name == "done" {
                        state.agent.done_call_id = Some(call.id.clone());
                        break;
                    }
                }
            }
            Event::Agent(WorkerEvent::Grabbed { parent_id, call }) => {
                state.agent.parent_id = Some(parent_id);
                state.agent.parent_call = Some(call);
            }
            _ => {}
        }
    }
}

// Link between Planner and Worker
#[derive(Clone)]
pub struct PlannerWorkerLink;

impl<ES: EventStore> Link<ES> for PlannerWorkerLink {
    type RuntimeA = PlannerAgent;
    type RuntimeB = WorkerAgent;

    async fn forward(
        &self,
        a_id: &str,
        event: &Event<PlannerEvent>,
        _handler: &Handler<AgentState<PlannerAgent>, ES>,
    ) -> Option<(String, Command<WorkerCommand>)> {
        match event {
            Event::Request(Request::ToolCalls { calls }) => {
                if let Some(call) = calls.iter().find(|call| call.function.name == "send_task") {
                    let worker_id = format!("task_{}", call.id);
                    return Some((
                        worker_id,
                        Command::Agent(WorkerCommand::Grab {
                            parent_id: a_id.to_owned(),
                            call: call.clone(),
                        }),
                    ));
                }
                None
            }
            _ => None,
        }
    }

    async fn backward(
        &self,
        _b_id: &str,
        event: &Event<WorkerEvent>,
        _handler: &Handler<AgentState<WorkerAgent>, ES>,
    ) -> Option<(String, Command<()>)> {
        match event {
            Event::Agent(WorkerEvent::Finished {
                parent_id,
                call,
                result,
            }) => {
                let result = serde_json::to_value(result).unwrap();
                let result = call.to_result(Ok(result));
                let command = Command::SendResponse(Response::ToolResults {
                    results: vec![result],
                });
                Some((parent_id.clone(), command))
            }
            _ => None,
        }
    }
}

fn send_task_tool_definition() -> ToolDefinition {
    ToolDefinition {
        name: "send_task".to_string(),
        description: "Send a task to a worker agent for execution".to_string(),
        parameters: serde_json::json!({
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "The task description for the worker"
                }
            },
            "required": ["description"]
        }),
    }
}

/// Test planner-worker workflow with Anthropic (Claude)
#[tokio::test]
async fn test_e2e_planner_anthropic() {
    dotenvy::dotenv().ok();
    if std::env::var("ANTHROPIC_API_KEY").is_err() {
        eprintln!("Skipping test_e2e_planner_anthropic: ANTHROPIC_API_KEY not set");
        return;
    }

    let result = timeout(
        Duration::from_secs(240),
        run_planner_workflow(
            "claude-sonnet-4-5-20250929",
            Arc::new(rig::providers::anthropic::Client::from_env().with_retry()),
            "anthropic_planner",
        ),
    )
    .await;

    match result {
        Ok(Ok(())) => eprintln!("✓ E2E planner test completed successfully with Anthropic"),
        Ok(Err(e)) => panic!("E2E planner test failed: {}", e),
        Err(_) => panic!("E2E planner test timed out after 240 seconds"),
    }
}

/// Test planner-worker workflow with OpenRouter (DeepSeek)
#[tokio::test]
async fn test_e2e_planner_openrouter() {
    dotenvy::dotenv().ok();
    if std::env::var("OPENROUTER_API_KEY").is_err() {
        eprintln!("Skipping test_e2e_planner_openrouter: OPENROUTER_API_KEY not set");
        return;
    }

    let result = timeout(
        Duration::from_secs(240),
        run_planner_workflow(
            "deepseek/deepseek-v3.2-exp",
            Arc::new(rig::providers::openrouter::Client::from_env().with_retry()),
            "openrouter_planner",
        ),
    )
    .await;

    match result {
        Ok(Ok(())) => eprintln!("✓ E2E planner test completed successfully with OpenRouter"),
        Ok(Err(e)) => panic!("E2E planner test failed: {}", e),
        Err(_) => panic!("E2E planner test timed out after 240 seconds"),
    }
}

async fn run_planner_workflow(
    model: &str,
    client: Arc<dyn LLMClientDyn>,
    planner_id: &str,
) -> Result<()> {
    let store = create_test_store().await;

    let planner_prompt = "
You are a planning assistant.
Use the 'send_task' tool to delegate work to a worker agent.
";

    let worker_prompt = "
You are a python software engineer.
Workspace is already set up using uv init.
Use uv package manager if you need to add extra libraries.
Program will be run using uv run main.py command.
IMPORTANT: After the script runs successfully, you MUST call the 'done' tool to complete the task.
";

    let user_prompt = "Create a simple Python script that prints 'Hello from E2E Test!' and the result of 5+5";

    // Setup planner
    let planner_llm = LLMHandler::new(
        client.clone(),
        LLMConfig {
            model: model.to_string(),
            preamble: Some(planner_prompt.to_string()),
            tools: Some(vec![send_task_tool_definition()]),
            ..Default::default()
        },
    );
    let mut planner_runtime = Runtime::<PlannerAgent, _>::new(store.clone(), ())
        .with_handler(planner_llm);

    // Setup worker
    let worker_tools = toolset(PythonValidator);
    let worker_llm = LLMHandler::new(
        client,
        LLMConfig {
            model: model.to_string(),
            preamble: Some(worker_prompt.to_string()),
            tools: Some(worker_tools.iter().map(|tool| tool.definition()).collect()),
            ..Default::default()
        },
    );
    let worker_tool_handler = ToolHandler::new(
        worker_tools,
        SandboxHandle::new(Default::default()),
        TemplateConfig::default_dir(get_dockerfile_dir_from_src_ws()),
    );
    let mut worker_runtime = Runtime::<WorkerAgent, _>::new(store.clone(), ())
        .with_handler(worker_llm)
        .with_handler(worker_tool_handler);

    // Link planner and worker
    link_runtimes(&mut planner_runtime, &mut worker_runtime, PlannerWorkerLink);

    // Send initial task to planner
    let command = Command::SendRequest(Request::Completion {
        content: rig::OneOrMany::one(rig::message::UserContent::text(user_prompt)),
    });
    planner_runtime.handler.execute(planner_id, command).await?;

    // Start both runtimes in the background
    let planner_handle = tokio::spawn(async move { planner_runtime.start().await });
    let worker_handle = tokio::spawn(async move { worker_runtime.start().await });

    // Poll for the Finished event in the worker stream
    let mut interval = tokio::time::interval(Duration::from_millis(500));
    let start = tokio::time::Instant::now();
    let max_wait = Duration::from_secs(210);

    loop {
        interval.tick().await;

        // Check if we've timed out
        if start.elapsed() > max_wait {
            planner_handle.abort();
            worker_handle.abort();
            return Err(eyre::eyre!(
                "Workflow did not complete within {} seconds",
                max_wait.as_secs()
            ));
        }

        // Load all worker aggregates and check for any Finished event
        // Since we don't know the specific worker aggregate_id, we need to list all aggregates
        let sequence_nums = store.load_sequence_nums::<AgentState<WorkerAgent>>().await?;

        let mut finished = false;
        for (worker_id, _) in sequence_nums {
            let events = store.load_events::<AgentState<WorkerAgent>>(&worker_id).await?;
            if events.iter().any(|e| matches!(e.data, Event::Agent(WorkerEvent::Finished { .. }))) {
                finished = true;
                break;
            }
        }

        if finished {
            eprintln!("✓ Planner workflow completed - Worker Finished event detected");
            planner_handle.abort();
            worker_handle.abort();
            return Ok(());
        }

        // Check if runtimes have crashed
        if planner_handle.is_finished() || worker_handle.is_finished() {
            return Err(eyre::eyre!("Runtime terminated unexpectedly"));
        }
    }
}
