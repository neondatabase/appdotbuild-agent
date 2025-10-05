use dabgent_agent::processor::agent::{Agent, AgentError, AgentState, Command, Event};
use dabgent_agent::processor::link::{Link, Runtime, link_runtimes};
use dabgent_agent::processor::llm::{LLMConfig, LLMHandler};
use dabgent_agent::processor::tools::{
    TemplateConfig, ToolHandler, get_dockerfile_dir_from_src_ws,
};
use dabgent_agent::processor::utils::LogHandler;
use dabgent_agent::toolbox::{self, basic::toolset};
use dabgent_mq::db::sqlite::SqliteStore;
use dabgent_mq::{Envelope, Event as MQEvent, EventStore, Handler, PollingQueue};
use dabgent_sandbox::SandboxHandle;
use eyre::Result;
use rig::client::ProviderClient;
use rig::completion::ToolDefinition;
use rig::message::{Text, ToolCall, ToolResult, ToolResultContent, UserContent};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

const MODEL: &str = "claude-sonnet-4-5-20250929";

const PLANNER_PROMPT: &str = "
You are a planning assistant.
Use the 'send_task' tool to delegate work to a worker agent.
";

const WORKER_PROMPT: &str = "
You are a python software engineer.
Workspace is already set up using uv init.
Use uv package manager if you need to add extra libraries.
Program will be run using uv run main.py command in the current directory.
";

const USER_PROMPT: &str = "
Create a minimal Python script that fetches my IP using ipify.org API
";

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();
    run_planner_worker().await.unwrap();
}

pub async fn run_planner_worker() -> Result<()> {
    let store = store().await;

    let planner_llm = LLMHandler::new(
        Arc::new(rig::providers::anthropic::Client::from_env()),
        LLMConfig {
            model: MODEL.to_string(),
            preamble: Some(PLANNER_PROMPT.to_string()),
            tools: Some(vec![send_task_tool_definition()]),
            ..Default::default()
        },
    );
    let mut planner_runtime = Runtime::<AgentState<Planner>, _>::new(store.clone(), ())
        .with_handler(planner_llm)
        .with_handler(LogHandler);

    let worker_tools = toolset(Validator);
    let worker_llm = LLMHandler::new(
        Arc::new(rig::providers::anthropic::Client::from_env()),
        LLMConfig {
            model: MODEL.to_string(),
            preamble: Some(WORKER_PROMPT.to_string()),
            tools: Some(worker_tools.iter().map(|tool| tool.definition()).collect()),
            ..Default::default()
        },
    );
    let worker_tool_handler = ToolHandler::new(
        worker_tools,
        SandboxHandle::new(Default::default()),
        TemplateConfig::default_dir(get_dockerfile_dir_from_src_ws()),
    );
    let mut worker_runtime = Runtime::<AgentState<Worker>, _>::new(store.clone(), ())
        .with_handler(worker_llm)
        .with_handler(worker_tool_handler)
        .with_handler(LogHandler);

    link_runtimes(&mut planner_runtime, &mut worker_runtime, PlannerWorkerLink);

    // Send initial task to planner before starting runtimes
    let command = Command::PutUserMessage {
        content: rig::OneOrMany::one(UserContent::text(USER_PROMPT)),
    };
    planner_runtime.handler.execute("planner", command).await?;

    let planner_handle = tokio::spawn(async move { planner_runtime.start().await });
    let worker_handle = tokio::spawn(async move { worker_runtime.start().await });

    tokio::select! {
        _ = planner_handle => {},
        _ = worker_handle => {},
    }

    Ok(())
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Planner;

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

impl Agent for Planner {
    const TYPE: &'static str = "planner";
    type AgentCommand = ();
    type AgentEvent = PlannerEvent;
    type AgentError = PlannerError;
    type Services = ();
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Worker {
    pub parent_id: Option<String>,
    pub parent_call: Option<ToolCall>,
    pub done_call_id: Option<String>,
}

impl Worker {
    fn is_success(&self, result: &ToolResult) -> bool {
        result.content.iter().any(|c| match c {
            ToolResultContent::Text(Text { text }) => text.contains("success"),
            _ => false,
        })
    }

    fn is_done(&self, results: &[ToolResult]) -> bool {
        self.done_call_id.as_ref().map_or(false, |id| {
            results
                .iter()
                .find(|r| &r.id == id)
                .map_or(false, |r| self.is_success(r))
        })
    }
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

impl Agent for Worker {
    const TYPE: &'static str = "worker";
    type AgentCommand = WorkerCommand;
    type AgentEvent = WorkerEvent;
    type AgentError = WorkerError;
    type Services = ();

    async fn handle(
        state: &AgentState<Self>,
        cmd: Command<Self::AgentCommand>,
        services: &Self::Services,
    ) -> Result<Vec<Event<Self::AgentEvent>>, AgentError<Self::AgentError>> {
        match cmd {
            Command::PutToolResults { results } if state.agent.is_done(&results) => {
                let mut events = state.shared_put_results(&results)?;
                events.push(Event::Agent(WorkerEvent::Finished {
                    parent_id: state.agent.parent_id.clone().unwrap(),
                    call: state.agent.parent_call.clone().unwrap(),
                    result: "task completed".to_string(),
                }));
                Ok(events)
            }
            Command::Agent(WorkerCommand::Grab { parent_id, call }) => {
                let args = &call.function.arguments;
                let description = args.get("description").unwrap().to_string();
                let content = rig::OneOrMany::one(UserContent::text(description));
                Ok(vec![
                    Event::Agent(WorkerEvent::Grabbed {
                        parent_id: parent_id.clone(),
                        call: call.clone(),
                    }),
                    Event::UserCompletion { content },
                ])
            }
            _ => state.handle_shared(cmd, services).await,
        }
    }

    fn apply(state: &mut AgentState<Self>, event: Event<Self::AgentEvent>) {
        state.apply_shared(event.clone());
        match event {
            Event::ToolCalls { ref calls } => {
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

#[derive(Clone)]
pub struct PlannerWorkerLink;

impl<ES: EventStore> Link<ES> for PlannerWorkerLink {
    type AggregateA = AgentState<Planner>;
    type AggregateB = AgentState<Worker>;

    async fn forward(
        &self,
        envelope: &Envelope<AgentState<Planner>>,
        _handler: &Handler<AgentState<Planner>, ES>,
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
        envelope: &Envelope<AgentState<Worker>>,
        _handler: &Handler<AgentState<Worker>, ES>,
    ) -> Option<(String, Command<()>)> {
        use dabgent_agent::toolbox::ToolCallExt;
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

async fn store() -> PollingQueue<SqliteStore> {
    let pool = sqlx::SqlitePool::connect(":memory:")
        .await
        .expect("Failed to create in-memory SQLite pool");
    let store = SqliteStore::new(pool, "agent");
    store.migrate().await;
    PollingQueue::new(store)
}

pub struct Validator;

impl toolbox::Validator for Validator {
    async fn run(
        &self,
        sandbox: &mut dabgent_sandbox::DaggerSandbox,
    ) -> Result<Result<(), String>> {
        use dabgent_sandbox::Sandbox;
        sandbox.exec("uv run main.py").await.map(|result| {
            if result.exit_code == 0 {
                Ok(())
            } else {
                Err(format!(
                    "code: {}\nstdout: {}\nstderr: {}",
                    result.exit_code, result.stdout, result.stderr
                ))
            }
        })
    }
}
