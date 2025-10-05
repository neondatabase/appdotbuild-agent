use dabgent_agent::processor::agent::{Agent, AgentState};
use dabgent_agent::processor::link::Runtime;
use dabgent_agent::processor::llm::{LLMConfig, LLMHandler};
use dabgent_agent::processor::tools::{
    TemplateConfig, ToolHandler, get_dockerfile_dir_from_src_ws,
};
use dabgent_agent::processor::utils::LogHandler;
use dabgent_agent::toolbox::{self, basic::toolset};
use dabgent_cli::App;
use dabgent_mq::db::sqlite::SqliteStore;
use dabgent_mq::{Event as MQEvent, PollingQueue};
use dabgent_sandbox::SandboxHandle;
use eyre::Result;
use rig::client::ProviderClient;
use serde::{Deserialize, Serialize};
use std::sync::Arc;

const MODEL: &str = "claude-sonnet-4-5-20250929";
const AGGREGATE_ID: &str = "agent";

const SYSTEM_PROMPT: &str = "
You are a python software engineer.
Workspace is already set up using uv init.
Use uv package manager if you need to add extra libraries.
Program will be run using uv run main.py command in the current directory.
";

#[tokio::main]
async fn main() {
    run_agent_with_cli().await.unwrap();
}

pub async fn run_agent_with_cli() -> Result<()> {
    let _ = dotenvy::dotenv();
    let store = store().await;

    // Setup Runtime with all handlers
    let worker_tools = toolset(Validator);
    let worker_llm = LLMHandler::new(
        Arc::new(rig::providers::anthropic::Client::from_env()),
        LLMConfig {
            model: MODEL.to_string(),
            preamble: Some(SYSTEM_PROMPT.to_string()),
            tools: Some(worker_tools.iter().map(|tool| tool.definition()).collect()),
            ..Default::default()
        },
    );
    let worker_tool_handler = ToolHandler::new(
        worker_tools,
        SandboxHandle::new(Default::default()),
        TemplateConfig::default_dir(get_dockerfile_dir_from_src_ws()),
    );
    let mut runtime = Runtime::<AgentState<Worker>, _>::new(store.clone(), ())
        .with_handler(worker_llm)
        .with_handler(worker_tool_handler)
        .with_handler(LogHandler);

    // the single line required to set up the CLI
    let app = App::new(&mut runtime, AGGREGATE_ID.to_string())?;

    tokio::select! {
        res = runtime.start() => res,
        res = app.run(ratatui::init()) => res,
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Worker;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum WorkerEvent {}

impl MQEvent for WorkerEvent {
    fn event_type(&self) -> String {
        "worker".to_string()
    }

    fn event_version(&self) -> String {
        "1.0".to_string()
    }
}

#[derive(Debug, thiserror::Error)]
pub enum WorkerError {}

impl Agent for Worker {
    const TYPE: &'static str = "worker";
    type AgentCommand = ();
    type AgentEvent = WorkerEvent;
    type AgentError = WorkerError;
    type Services = ();
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
