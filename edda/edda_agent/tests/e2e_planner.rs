mod common;

use common::{PythonValidator, create_test_store};
use edda_agent::llm::{LLMClient, LLMProvider, WithRetryExt};
use edda_agent::processor::agent::{Agent, AgentState, Command, Event};
use edda_agent::processor::link::{Link, Runtime, link_runtimes};
use edda_agent::processor::llm::{LLMConfig, LLMHandler};
use edda_agent::processor::tools::{
    TemplateConfig, ToolHandler, get_dockerfile_dir_from_src_ws,
};
use edda_agent::toolbox::{ToolCallExt, basic::toolset};
use edda_mq::{Envelope, Event as MQEvent, EventStore, Handler};
use edda_sandbox::SandboxHandle;
use eyre::Result;
use rig::completion::ToolDefinition;
use rig::message::{ToolCall, ToolResult, ToolResultContent, UserContent};
use serde::{Deserialize, Serialize};
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

impl WorkerAgent {
    fn is_success(&self, result: &ToolResult) -> bool {
        result.content.iter().any(|c| match c {
            ToolResultContent::Text(text) => text.text.contains("success"),
            _ => false,
        })
    }

    fn is_done(&self, results: &[ToolResult]) -> bool {
        self.done_call_id.as_ref().is_some_and(|id| {
            results
                .iter()
                .find(|r| &r.id == id)
                .is_some_and(|r| self.is_success(r))
        })
    }
}

impl Agent for WorkerAgent {
    const TYPE: &'static str = "e2e_worker";
    type AgentCommand = WorkerCommand;
    type AgentEvent = WorkerEvent;
    type AgentError = WorkerError;
    type Services = ();

    async fn handle(
        state: &AgentState<Self>,
        cmd: Command<Self::AgentCommand>,
        services: &Self::Services,
    ) -> Result<Vec<Event<Self::AgentEvent>>, edda_agent::processor::agent::AgentError<Self::AgentError>> {
        match cmd {
            Command::Agent(WorkerCommand::Grab { parent_id, call }) => {
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
                    Event::UserCompletion { content },
                ])
            }
            Command::PutToolResults { results } if state.agent.is_done(&results) => {
                let mut events = state.shared_put_results(&results)?;
                events.push(Event::Agent(WorkerEvent::Finished {
                    parent_id: state.agent.parent_id.clone().unwrap(),
                    call: state.agent.parent_call.clone().unwrap(),
                    result: "task completed".to_string(),
                }));
                Ok(events)
            }
            _ => state.handle_shared(cmd, services).await,
        }
    }

    fn apply(state: &mut AgentState<Self>, event: Event<Self::AgentEvent>) {
        match event {
            Event::ToolCalls { ref calls } => {
                for call in calls {
                    if call.function.name == "done" {
                        state.agent.done_call_id = Some(call.id.clone());
                        break;
                    }
                }
                state.apply_shared(event);
            }
            Event::Agent(WorkerEvent::Grabbed { parent_id, call }) => {
                state.agent.parent_id = Some(parent_id);
                state.agent.parent_call = Some(call);
            }
            _ => state.apply_shared(event),
        }
    }
}

// Link between Planner and Worker
#[derive(Clone)]
pub struct PlannerWorkerLink;

impl<ES: EventStore> Link<ES> for PlannerWorkerLink {
    type AggregateA = AgentState<PlannerAgent>;
    type AggregateB = AgentState<WorkerAgent>;

    async fn forward(
        &self,
        envelope: &Envelope<Self::AggregateA>,
        _handler: &Handler<Self::AggregateA, ES>,
    ) -> Option<(String, Command<WorkerCommand>)> {
        match &envelope.data {
            Event::ToolCalls { calls } => {
                if let Some(call) = calls.iter().find(|call| call.function.name == "send_task") {
                    let worker_id = format!("task_{}", call.id);
                    return Some((
                        worker_id,
                        Command::Agent(WorkerCommand::Grab {
                            parent_id: envelope.aggregate_id.clone(),
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
        envelope: &Envelope<Self::AggregateB>,
        _handler: &Handler<Self::AggregateB, ES>,
    ) -> Option<(String, Command<()>)> {
        match &envelope.data {
            Event::Agent(WorkerEvent::Finished {
                parent_id,
                call,
                result,
            }) => {
                let result = serde_json::to_value(result).unwrap();
                let result = call.to_result(Ok(result));
                let command = Command::PutToolResults {
                    results: vec![result],
                };
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
#[cfg_attr(not(feature = "dagger"), ignore)]
async fn test_e2e_planner_anthropic() {
    test_e2e_planner_impl(
        "test_e2e_planner_anthropic",
        LLMProvider::Anthropic,
        "anthropic_planner",
    )
    .await
}

async fn test_e2e_planner_impl(test_name: &str, llm_provider: LLMProvider, planner_id: &str) {
    dotenvy::dotenv().ok();
    if !llm_provider.is_api_key_env_var_set() {
        eprintln!(
            "Skipping {test_name}: env var {} not set",
            llm_provider.api_key_env_var()
        );
        return;
    }

    let result = timeout(
        Duration::from_secs(240),
        run_planner_workflow(llm_provider, planner_id),
    )
    .await;

    match result {
        Ok(Ok(())) => eprintln!(
            "✓ E2E planner test completed successfully with {}",
            llm_provider.name()
        ),
        Ok(Err(e)) => panic!("E2E planner test failed: {}", e),
        Err(_) => panic!("E2E planner test timed out after 240 seconds"),
    }
}

async fn run_planner_workflow(llm_provider: LLMProvider, planner_id: &str) -> Result<()> {
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

    let user_prompt =
        "Create a simple Python script that prints 'Hello from E2E Test!' and the result of 5+5";

    let client = llm_provider.client_from_env_raw().with_retry().into_arc();

    // Setup planner
    let planner_llm = LLMHandler::new(
        client.clone(),
        LLMConfig {
            model: llm_provider.default_model().to_string(),
            preamble: Some(planner_prompt.to_string()),
            tools: Some(vec![send_task_tool_definition()]),
            ..Default::default()
        },
    );
    let mut planner_runtime =
        Runtime::<AgentState<PlannerAgent>, _>::new(store.clone(), ()).with_handler(planner_llm);

    // Setup worker
    let worker_tools = toolset(PythonValidator);
    let worker_llm = LLMHandler::new(
        client,
        LLMConfig {
            model: llm_provider.default_model().to_string(),
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
    let mut worker_runtime = Runtime::<AgentState<WorkerAgent>, _>::new(store.clone(), ())
        .with_handler(worker_llm)
        .with_handler(worker_tool_handler);

    // Link planner and worker
    link_runtimes(&mut planner_runtime, &mut worker_runtime, PlannerWorkerLink);

    // Send initial task to planner
    let command = Command::PutUserMessage {
        content: rig::OneOrMany::one(rig::message::UserContent::text(user_prompt)),
    };
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
        let sequence_nums = store
            .load_sequence_nums::<AgentState<WorkerAgent>>()
            .await?;

        let mut finished = false;
        for (worker_id, _) in sequence_nums {
            let events = store
                .load_events::<AgentState<WorkerAgent>>(&worker_id)
                .await?;
            if events
                .iter()
                .any(|e| matches!(e.data, Event::Agent(WorkerEvent::Finished { .. })))
            {
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
        if planner_handle.is_finished() {
            let result = planner_handle.await.expect("planner runtime task panicked");
            return Err(eyre::eyre!("Planner runtime terminated unexpectedly: {:?}", result));
        }
        if worker_handle.is_finished() {
            let result = worker_handle.await.expect("worker runtime task panicked");
            return Err(eyre::eyre!("Worker runtime terminated unexpectedly: {:?}", result));
        }
    }
}
