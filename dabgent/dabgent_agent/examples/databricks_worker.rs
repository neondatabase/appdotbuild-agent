use dabgent_agent::processor::agent::{Agent, AgentError, AgentState, Command, Event};
use dabgent_agent::processor::databricks::{
    self, DatabricksTool, DatabricksToolHandler, FinishDelegation, FinishDelegationArgs,
};
use dabgent_agent::processor::link::{Link, Runtime, link_runtimes};
use dabgent_agent::processor::llm::{LLMConfig, LLMHandler};
use dabgent_agent::processor::utils::LogHandler;
use dabgent_integrations::databricks::DatabricksRestClient;
use dabgent_mq::db::sqlite::SqliteStore;
use dabgent_mq::{Envelope, Event as MQEvent, EventStore, Handler, PollingQueue};
use eyre::Result;
use rig::client::ProviderClient;
use rig::completion::ToolDefinition;
use rig::message::{ToolCall, UserContent};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

const MODEL: &str = "claude-sonnet-4-5-20250929";

const MAIN_PROMPT: &str = "
You are an AI assistant that helps users understand Databricks catalogs.
Use the 'explore_databricks_catalog' tool to delegate exploration tasks to a specialist.
";

const DATABRICKS_PROMPT: &str = "
You are a Databricks catalog explorer. Explore Unity Catalog to understand data structures.

## Your Task
Explore the specified catalog and provide comprehensive summary of:
- Available schemas and purposes
- Tables with descriptions
- Column structures including names, types, sample values
- Relationships between tables

## Focus
- Look for business-relevant data
- Identify primary/foreign keys
- Use `databricks_describe_table` for full column details
- Note columns for API fields

## Completion
When done, call `finish_delegation` with comprehensive summary including:
- Overview of discoveries
- Key schemas and table counts
- Detailed table structures with column specs
- API endpoint recommendations with column mappings

IMPORTANT: Always use `databricks_describe_table` to get complete column details.
";

const USER_PROMPT: &str = "
Explore the 'main' catalog in Databricks and tell me about any bakery or sales data.
";

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();
    run_databricks_worker().await.unwrap();
}

pub async fn run_databricks_worker() -> Result<()> {
    let store = store().await;

    // Main agent setup
    let main_llm = LLMHandler::new(
        Arc::new(rig::providers::anthropic::Client::from_env()),
        LLMConfig {
            model: MODEL.to_string(),
            preamble: Some(MAIN_PROMPT.to_string()),
            tools: Some(vec![explore_databricks_tool_definition()]),
            ..Default::default()
        },
    );
    let mut main_runtime = Runtime::<AgentState<MainAgent>, _>::new(store.clone(), ())
        .with_handler(main_llm)
        .with_handler(LogHandler);

    // Databricks worker setup
    let tools = databricks::toolbox();
    let databricks_client =
        Arc::new(DatabricksRestClient::new().map_err(|e| eyre::eyre!("{}", e))?);
    let databricks_llm = LLMHandler::new(
        Arc::new(rig::providers::anthropic::Client::from_env()),
        LLMConfig {
            model: MODEL.to_string(),
            preamble: Some(DATABRICKS_PROMPT.to_string()),
            tools: Some(tools.iter().map(|tool| tool.definition()).collect()),
            ..Default::default()
        },
    );
    let databricks_tool_handler = DatabricksToolHandler::new(databricks_client, tools);
    let mut databricks_runtime = Runtime::<AgentState<DatabricksWorker>, _>::new(store.clone(), ())
        .with_handler(databricks_llm)
        .with_handler(databricks_tool_handler)
        .with_handler(LogHandler);

    link_runtimes(&mut main_runtime, &mut databricks_runtime, DatabricksLink);

    // Send initial task
    let command = Command::PutUserMessage {
        content: rig::OneOrMany::one(UserContent::text(USER_PROMPT)),
    };
    main_runtime.handler.execute("main", command).await?;

    let main_handle = tokio::spawn(async move { main_runtime.start().await });
    let databricks_handle = tokio::spawn(async move { databricks_runtime.start().await });

    tokio::select! {
        _ = main_handle => {},
        _ = databricks_handle => {},
    }

    Ok(())
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

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DatabricksWorker {
    pub parent_id: Option<String>,
    pub parent_call: Option<ToolCall>,
}

impl DatabricksWorker {
    fn finish_args_opt(&self, calls: &[ToolCall]) -> Option<FinishDelegationArgs> {
        for call in calls.iter().map(|c| &c.function) {
            if call.name == FinishDelegation.name() {
                let args = serde_json::from_value(call.arguments.clone());
                return Some(args.unwrap());
            }
        }
        None
    }

    fn emit_finished(&self, summary: String) -> Event<DatabricksEvent> {
        let event = DatabricksEvent::Finished {
            parent_id: self.parent_id.clone().unwrap(),
            call: self.parent_call.clone().unwrap(),
            summary,
        };
        Event::Agent(event)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum DatabricksEvent {
    Grabbed {
        parent_id: String,
        call: ToolCall,
    },
    Finished {
        parent_id: String,
        call: ToolCall,
        summary: String,
    },
}

impl MQEvent for DatabricksEvent {
    fn event_type(&self) -> String {
        match self {
            DatabricksEvent::Grabbed { .. } => "grabbed".to_string(),
            DatabricksEvent::Finished { .. } => "finished".to_string(),
        }
    }

    fn event_version(&self) -> String {
        "1.0".to_string()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum DatabricksCommand {
    Explore { parent_id: String, call: ToolCall },
}

#[derive(Debug, thiserror::Error)]
pub enum DatabricksError {}

impl Agent for DatabricksWorker {
    const TYPE: &'static str = "databricks_worker";
    type AgentCommand = DatabricksCommand;
    type AgentEvent = DatabricksEvent;
    type AgentError = DatabricksError;
    type Services = ();

    async fn handle(
        state: &AgentState<Self>,
        cmd: Command<Self::AgentCommand>,
        services: &Self::Services,
    ) -> Result<Vec<Event<Self::AgentEvent>>, AgentError<Self::AgentError>> {
        match cmd {
            Command::PutToolCalls { calls } => {
                if let Some(args) = state.agent.finish_args_opt(&calls) {
                    return Ok(vec![state.agent.emit_finished(args.summary)]);
                }
                Ok(vec![Event::ToolCalls { calls }])
            }
            Command::Agent(DatabricksCommand::Explore { parent_id, call }) => {
                let args = &call.function.arguments;
                let args: ExploreCatalogArgs = serde_json::from_value(args.clone()).unwrap();
                let description = format!("Explore catalog '{}': {}", args.catalog, args.prompt);
                let content = rig::OneOrMany::one(UserContent::text(description));
                Ok(vec![
                    Event::Agent(DatabricksEvent::Grabbed {
                        parent_id: parent_id.clone(),
                        call: call.clone(),
                    }),
                    Event::UserCompletion { content },
                ])
            }
            _ => state.handle_shared(cmd, services).await,
        }
    }
}

#[derive(Clone)]
pub struct DatabricksLink;

impl DatabricksLink {
    fn trigger_call_opt(&self, calls: &[ToolCall]) -> Option<ToolCall> {
        let trigger = explore_databricks_tool_definition();
        for call in calls.iter() {
            if call.function.name == trigger.name {
                return Some(call.clone());
            }
        }
        None
    }
}

impl<ES: EventStore> Link<ES> for DatabricksLink {
    type AggregateA = AgentState<MainAgent>;
    type AggregateB = AgentState<DatabricksWorker>;

    async fn forward(
        &self,
        envelope: &Envelope<AgentState<MainAgent>>,
        _handler: &Handler<AgentState<MainAgent>, ES>,
    ) -> Option<(String, Command<DatabricksCommand>)> {
        match &envelope.data {
            Event::ToolCalls { calls } => {
                if let Some(call) = self.trigger_call_opt(&calls) {
                    let worker_id = format!("databricks_{}", call.id);
                    return Some((
                        worker_id,
                        Command::Agent(DatabricksCommand::Explore {
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
        envelope: &Envelope<AgentState<DatabricksWorker>>,
        _handler: &Handler<AgentState<DatabricksWorker>, ES>,
    ) -> Option<(String, Command<()>)> {
        use dabgent_agent::toolbox::ToolCallExt;
        match &envelope.data {
            Event::Agent(DatabricksEvent::Finished {
                parent_id,
                call,
                summary,
            }) => {
                let result = serde_json::to_value(summary).unwrap();
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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExploreCatalogArgs {
    pub catalog: String,
    pub prompt: String,
}

fn explore_databricks_tool_definition() -> ToolDefinition {
    ToolDefinition {
        name: "explore_databricks_catalog".to_string(),
        description: "Explore a Databricks catalog to understand data structure".to_string(),
        parameters: serde_json::json!({
            "type": "object",
            "properties": {
                "catalog": {
                    "type": "string",
                    "description": "Catalog name to explore"
                },
                "prompt": {
                    "type": "string",
                    "description": "What to look for in the catalog"
                }
            },
            "required": ["catalog", "prompt"]
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
