use dabgent_agent::processor::agent::{Agent, AgentState};
use dabgent_agent::processor::databricks::*;
use dabgent_agent::processor::link::Runtime;
use dabgent_agent::processor::llm::{LLMConfig, LLMHandler};
use dabgent_agent::processor::utils::LogHandler;
use dabgent_cli::App;
use dabgent_integrations::databricks::DatabricksRestClient;
use dabgent_mq::db::sqlite::SqliteStore;
use dabgent_mq::{Event as MQEvent, PollingQueue};
use eyre::Result;
use rig::client::ProviderClient;
use serde::{Deserialize, Serialize};
use std::sync::Arc;

const AGGREGATE_ID: &str = "databricks";

const MODEL: &str = "claude-sonnet-4-5-20250929";

const MAIN_PROMPT: &str = "
You are an AI assistant that helps users understand Databricks catalogs.

## Focus
- Look for business-relevant data
- Identify primary/foreign keys
- Use `databricks_describe_table` for full column details
- Note columns for API fields

IMPORTANT: Always use `databricks_describe_table` to get complete column details.
";

#[tokio::main]
async fn main() {
    run_databricks_worker().await.unwrap();
}

pub async fn run_databricks_worker() -> Result<()> {
    let store = store().await;

    // Main agent setup
    let tools = toolbox();
    let main_llm = LLMHandler::new(
        Arc::new(rig::providers::anthropic::Client::from_env()),
        LLMConfig {
            model: MODEL.to_string(),
            preamble: Some(MAIN_PROMPT.to_string()),
            tools: Some(tools.iter().map(|tool| tool.definition()).collect()),
            ..Default::default()
        },
    );
    let tool_handler = DatabricksToolHandler::new(
        Arc::new(DatabricksRestClient::new().map_err(|e| eyre::eyre!("{}", e))?),
        tools,
    );
    let mut runtime = Runtime::<AgentState<MainAgent>, _>::new(store.clone(), ())
        .with_handler(main_llm)
        .with_handler(tool_handler)
        .with_handler(LogHandler);

    let app = App::new(&mut runtime, AGGREGATE_ID.to_string())?;

    tokio::select! {
        res = runtime.start() => res,
        res = app.run(ratatui::init()) => res,
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct MainAgent;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum MainEvent {}

impl MQEvent for MainEvent {
    fn event_type(&self) -> String {
        "main".to_string()
    }

    fn event_version(&self) -> String {
        "1.0".to_string()
    }
}

#[derive(Debug, thiserror::Error)]
pub enum MainError {}

impl Agent for MainAgent {
    const TYPE: &'static str = "main";
    type AgentCommand = ();
    type AgentEvent = MainEvent;
    type AgentError = MainError;
    type Services = ();
}

pub fn toolbox() -> Vec<Box<dyn DatabricksToolDyn>> {
    let tools: Vec<Box<dyn DatabricksToolDyn>> = vec![
        Box::new(DatabricksListCatalogs),
        Box::new(DatabricksListSchemas),
        Box::new(DatabricksListTables),
        Box::new(DatabricksDescribeTable),
        Box::new(DatabricksExecuteQuery),
    ];
    tools
}

async fn store() -> PollingQueue<SqliteStore> {
    let pool = sqlx::SqlitePool::connect(":memory:")
        .await
        .expect("Failed to create in-memory SQLite pool");
    let store = SqliteStore::new(pool, "agent");
    store.migrate().await;
    PollingQueue::new(store)
}
