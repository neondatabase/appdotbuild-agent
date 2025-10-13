use dabgent_agent::processor::agent::{Agent, AgentError, AgentState, Command, Event};
// use dabgent_agent::processor::finish::FinishHandler;
use dabgent_agent::processor::link::Runtime;
use dabgent_agent::processor::llm::{LLMConfig, LLMHandler};
use dabgent_agent::processor::sandbox::{self, SandboxProvider, TemplateConfig, toolset};
use dabgent_agent::processor::tools::get_dockerfile_dir_from_src_ws;
use dabgent_agent::processor::utils::LogHandler;
use dabgent_agent::tool::ToolHandler;
use dabgent_mq::Event as MQEvent;
use dabgent_mq::db::sqlite::SqliteStore;
use dabgent_mq::listener::PollingQueue;
use dabgent_sandbox::{DaggerSandbox, Sandbox, SandboxHandle};
use eyre::Result;
use rig::client::ProviderClient;
use rig::message::{Text, ToolResult, ToolResultContent};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

const MODEL: &str = "claude-sonnet-4-5-20250929";

const SYSTEM_PROMPT: &str = "
You are a python software engineer.
Workspace is already set up using uv init.
Use uv package manager if you need to add extra libraries.
Program will be run using uv run main.py command.
When you finish the task, call the done tool to signal completion.
";

const USER_PROMPT: &str = "minimal script that fetches my ip using some api like ipify.org";

#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt::init();
    run_worker().await.unwrap();
}

pub async fn run_worker() -> Result<()> {
    let store = store().await;
    let tools = toolset(Validator);

    let llm = LLMHandler::new(
        Arc::new(rig::providers::anthropic::Client::from_env()),
        LLMConfig {
            model: MODEL.to_string(),
            preamble: Some(SYSTEM_PROMPT.to_string()),
            tools: Some(tools.iter().map(|tool| tool.definition()).collect()),
            ..Default::default()
        },
    );

    let sandbox_handle = SandboxHandle::new(Default::default());
    let template_config = TemplateConfig::default_dir(get_dockerfile_dir_from_src_ws());

    let tool_handler = ToolHandler::new(
        SandboxProvider {
            config: template_config,
            dagger: sandbox_handle,
        },
        tools,
    );

    let runtime = Runtime::<AgentState<Basic>, _>::new(store, ())
        .with_handler(llm)
        .with_handler(tool_handler);

    // Optionally enable artifact export if EXPORT_PATH is set
    // if let Ok(export_path) = std::env::var("EXPORT_PATH") {
    //     let tools_for_finish = toolset(Validator);
    //     let finish_handler = FinishHandler::new(
    //         sandbox_handle,
    //         export_path,
    //         tools_for_finish,
    //         template_config,
    //     );
    //     runtime = runtime.with_handler(finish_handler);
    // }

    let runtime = runtime.with_handler(LogHandler);

    let command = Command::PutUserMessage {
        content: rig::OneOrMany::one(rig::message::UserContent::text(USER_PROMPT)),
    };
    runtime.handler.execute("basic", command).await?;

    runtime.start().await
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Basic {
    pub done_call_id: Option<String>,
}

impl Basic {
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
pub enum BasicEvent {
    Finished,
}

impl MQEvent for BasicEvent {
    fn event_type(&self) -> String {
        match self {
            BasicEvent::Finished => "finished".to_string(),
        }
    }

    fn event_version(&self) -> String {
        "1.0".to_string()
    }
}

#[derive(Debug, thiserror::Error)]
pub enum BasicError {}

impl Agent for Basic {
    const TYPE: &'static str = "basic_worker";
    type AgentCommand = ();
    type AgentEvent = BasicEvent;
    type AgentError = BasicError;
    type Services = ();

    async fn handle(
        state: &AgentState<Self>,
        cmd: Command<Self::AgentCommand>,
        services: &Self::Services,
    ) -> Result<Vec<Event<Self::AgentEvent>>, AgentError<Self::AgentError>> {
        match cmd {
            Command::PutToolResults { results } if state.agent.is_done(&results) => {
                let mut events = state.shared_put_results(&results)?;
                events.push(Event::Agent(BasicEvent::Finished));
                Ok(events)
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
            _ => {}
        }
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

impl sandbox::Validator for Validator {
    async fn run(&self, sandbox: &mut DaggerSandbox) -> Result<Result<(), String>> {
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
