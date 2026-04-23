use edda_agent::llm::FinishReason;
use edda_agent::processor::agent::{Agent, AgentError, AgentState, Command, Event};
use edda_agent::processor::databricks::{
    self, DatabricksTool, DatabricksToolHandler, FinishDelegation, FinishDelegationArgs,
};
use edda_agent::processor::link::{Link, Runtime, link_runtimes};
use edda_agent::processor::llm::{LLMConfig, LLMHandler};
use edda_agent::processor::tools::{
    TemplateConfig, ToolHandler, get_dockerfile_dir_from_src_ws,
};
use edda_agent::processor::utils::LogHandler;
use edda_agent::toolbox::{self, basic::toolset};
use edda_integrations::databricks::DatabricksRestClient;
use edda_mq::store::{AnyStore, create_store};
use edda_mq::{Envelope, Event as MQEvent, EventStore, Handler, PollingQueue};
use edda_sandbox::SandboxHandle;
use eyre::Result;
use edda_agent::llm::{LLMClient, LLMProvider, WithRetryExt};
use rig::completion::ToolDefinition;
use rig::message::{Text, ToolCall, ToolResult, ToolResultContent, UserContent};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

// Prompts
const PLANNER_PROMPT: &str = "
You are a planning assistant that coordinates between different specialist agents.
You have two tools:
- 'explore_databricks_catalog' — delegates Databricks catalog exploration to a specialist
- 'send_coding_task' — delegates Python coding to a specialist

STRICT WORKFLOW — always follow these steps in order:
1. Call 'explore_databricks_catalog' to discover the data schema and SQL queries.
2. Wait for the exploration result, then immediately call 'send_coding_task' with a detailed
   description that includes the discovered table names, column names, and the exact SQL queries
   to use. Do NOT summarize or reply with text — call the tool.
3. Wait for the coding result confirming the task is complete.

Never respond with plain text when you have pending tool calls to make.
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
- Look for sales-relevant data (orders, revenue, products, customers)
- Identify primary/foreign keys
- Use `databricks_describe_table` for full column details
- Note exact table and column names needed to query sales stats

## Completion
When done, call `finish_delegation` with comprehensive summary including:
- Overview of discoveries
- Key schemas and table counts
- Detailed table structures with column specs and sample values
- Exact SQL queries that could compute: total revenue, top products, sales by period

IMPORTANT: Always use `databricks_describe_table` to get complete column details.
";

const CODING_WORKER_PROMPT: &str = "
You are a python software engineer.
Workspace is already set up using uv init.
Use uv package manager if you need to add extra libraries.
Program will be run using uv run main.py command in the current directory.

Your task is to build a CLI tool that reports core sales statistics from a Databricks SQL warehouse.
Use the databricks-sql-connector library to query the data.
The report should print to stdout: total revenue, top 5 products by revenue, and sales breakdown by period.
Use the DATABRICKS_HOST, DATABRICKS_TOKEN, and DATABRICKS_WAREHOUSE_ID environment variables for connection.
Format output as a readable text report with clear sections and aligned columns.

IMPORTANT: After the script runs successfully, you MUST call the 'done' tool to complete the task.
";

const USER_PROMPT: &str = "
Explore the 'main' catalog in Databricks and find sales or bakery data with revenue/order information.
Then build a Python CLI tool that connects to Databricks and prints a sales statistics report:
total revenue, top 5 products by revenue, and sales breakdown by time period.
";

#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    // Choose provider via environment variable
    let provider = std::env::var("LLM_PROVIDER")
        .unwrap_or_else(|_| "anthropic".to_string())
        .to_lowercase();

    let provider = match provider.as_str() {
        "openrouter" => LLMProvider::OpenRouter,
        _ => LLMProvider::Anthropic,
    };

    run_multi_agent_system(provider).await.unwrap();
}

pub async fn run_multi_agent_system(provider: LLMProvider) -> Result<()> {
    let store = store().await;

    // === Planner Agent Setup ===
    let planner_llm = create_llm_handler(
        provider,
        PLANNER_PROMPT,
        vec![
            explore_databricks_tool_definition(),
            send_coding_task_tool_definition(),
        ],
    );

    let mut planner_runtime = Runtime::<AgentState<Planner>, _>::new(store.clone(), ())
        .with_handler(planner_llm)
        .with_handler(LogHandler);

    // === Databricks Worker Setup ===
    let databricks_tools = databricks::toolbox();
    let databricks_client =
        Arc::new(DatabricksRestClient::new().map_err(|e| eyre::eyre!("{}", e))?);

    let databricks_llm = create_llm_handler(
        provider,
        DATABRICKS_PROMPT,
        databricks_tools.iter().map(|tool| tool.definition()).collect(),
    );

    let databricks_tool_handler = DatabricksToolHandler::new(databricks_client, databricks_tools);
    let mut databricks_runtime = Runtime::<AgentState<DatabricksWorker>, _>::new(store.clone(), ())
        .with_handler(databricks_llm)
        .with_handler(databricks_tool_handler)
        .with_handler(LogHandler);

    // === Coding Worker Setup ===
    let coding_tools = toolset(Validator);
    let coding_llm = create_llm_handler(
        provider,
        CODING_WORKER_PROMPT,
        coding_tools.iter().map(|tool| tool.definition()).collect(),
    );

    let coding_tool_handler = ToolHandler::new(
        coding_tools,
        SandboxHandle::new(Default::default()),
        TemplateConfig::default_dir(get_dockerfile_dir_from_src_ws()),
    );

    let mut coding_runtime = Runtime::<AgentState<CodingWorker>, _>::new(store.clone(), ())
        .with_handler(coding_llm)
        .with_handler(coding_tool_handler)
        .with_handler(LogHandler);

    // === Link Agents ===
    link_runtimes(&mut planner_runtime, &mut databricks_runtime, DatabricksLink);
    link_runtimes(&mut planner_runtime, &mut coding_runtime, CodingLink);

    // === Start System ===
    let command = Command::PutUserMessage {
        content: rig::OneOrMany::one(UserContent::text(USER_PROMPT)),
    };
    planner_runtime.handler.execute("planner", command).await?;

    let planner_handle = tokio::spawn(async move { planner_runtime.start().await });
    let databricks_handle = tokio::spawn(async move { databricks_runtime.start().await });
    let coding_handle = tokio::spawn(async move { coding_runtime.start().await });

    tokio::select! {
        _ = planner_handle => {},
        _ = databricks_handle => {},
        _ = coding_handle => {},
    }

    Ok(())
}

fn create_llm_handler(
    provider: LLMProvider,
    preamble: &str,
    tools: Vec<ToolDefinition>,
) -> LLMHandler {
    LLMHandler::new(
        provider.client_from_env_raw().with_retry().into_arc(),
        LLMConfig {
            model: provider.default_model().to_string(),
            preamble: Some(preamble.to_string()),
            tools: Some(tools),
            ..Default::default()
        },
    )
}

// ============================================================================
// Planner Agent
// ============================================================================

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

    async fn handle(
        state: &AgentState<Self>,
        cmd: Command<Self::AgentCommand>,
        services: &Self::Services,
    ) -> Result<Vec<Event<Self::AgentEvent>>, AgentError<Self::AgentError>> {
        if let Command::PutCompletion { ref response } = cmd {
            if response.finish_reason == FinishReason::Stop {
                // LLM replied with text instead of calling a tool — re-prompt it
                let mut events = state.handle_shared(cmd, services).await?;
                events.push(Event::UserCompletion {
                    content: rig::OneOrMany::one(UserContent::text(
                        "You must call one of your tools now. \
                         If you have already received Databricks exploration results, \
                         call 'send_coding_task' immediately with a detailed description \
                         including the discovered table names, column names, and SQL queries. \
                         Do not respond with plain text.",
                    )),
                });
                return Ok(events);
            }
        }
        state.handle_shared(cmd, services).await
    }
}

// ============================================================================
// Databricks Worker Agent
// ============================================================================

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
            Command::PutCompletion { ref response }
                if response.finish_reason == FinishReason::Stop
                    && state.agent.parent_id.is_some() =>
            {
                // LLM finished with text instead of calling finish_delegation — treat text as summary
                let summary = response
                    .choice
                    .iter()
                    .filter_map(|c| match c {
                        rig::message::AssistantContent::Text(t) => Some(t.text.clone()),
                        _ => None,
                    })
                    .collect::<Vec<_>>()
                    .join("\n");
                let mut events = state.handle_shared(cmd, services).await?;
                events.push(state.agent.emit_finished(summary));
                Ok(events)
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

    fn apply(state: &mut AgentState<Self>, event: Event<Self::AgentEvent>) {
        state.apply_shared(event.clone());
        if let Event::Agent(DatabricksEvent::Grabbed { parent_id, call }) = event {
            state.agent.parent_id = Some(parent_id);
            state.agent.parent_call = Some(call);
        }
    }
}

// ============================================================================
// Coding Worker Agent
// ============================================================================

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct CodingWorker {
    pub parent_id: Option<String>,
    pub parent_call: Option<ToolCall>,
    pub done_call_id: Option<String>,
}

impl CodingWorker {
    fn is_success(&self, result: &ToolResult) -> bool {
        result.content.iter().any(|c| match c {
            ToolResultContent::Text(Text { text }) => text.contains("success"),
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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum CodingEvent {
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

impl MQEvent for CodingEvent {
    fn event_type(&self) -> String {
        match self {
            CodingEvent::Grabbed { .. } => "grabbed".to_string(),
            CodingEvent::Finished { .. } => "finished".to_string(),
        }
    }

    fn event_version(&self) -> String {
        "1.0".to_string()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum CodingCommand {
    Execute { parent_id: String, call: ToolCall },
}

#[derive(Debug, thiserror::Error)]
pub enum CodingError {}

impl Agent for CodingWorker {
    const TYPE: &'static str = "coding_worker";
    type AgentCommand = CodingCommand;
    type AgentEvent = CodingEvent;
    type AgentError = CodingError;
    type Services = ();

    async fn handle(
        state: &AgentState<Self>,
        cmd: Command<Self::AgentCommand>,
        services: &Self::Services,
    ) -> Result<Vec<Event<Self::AgentEvent>>, AgentError<Self::AgentError>> {
        match cmd {
            Command::PutToolResults { results } if state.agent.is_done(&results) => {
                let mut events = state.shared_put_results(&results)?;
                events.push(Event::Agent(CodingEvent::Finished {
                    parent_id: state.agent.parent_id.clone().unwrap(),
                    call: state.agent.parent_call.clone().unwrap(),
                    result: "task completed".to_string(),
                }));
                Ok(events)
            }
            Command::PutCompletion { ref response }
                if response.finish_reason == FinishReason::Stop
                    || response.finish_reason == FinishReason::MaxTokens =>
            {
                let mut events = state.handle_shared(cmd, services).await?;
                events.push(Event::UserCompletion {
                    content: rig::OneOrMany::one(UserContent::text(
                        "You must call a tool now. \
                         When the script runs successfully, call 'done'. \
                         If there are errors, fix them with the available tools first.",
                    )),
                });
                Ok(events)
            }
            Command::Agent(CodingCommand::Execute { parent_id, call }) => {
                let args = &call.function.arguments;
                let description = args.get("description").unwrap().as_str().unwrap();
                let content = rig::OneOrMany::one(UserContent::text(description));
                Ok(vec![
                    Event::Agent(CodingEvent::Grabbed {
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
            Event::Agent(CodingEvent::Grabbed { parent_id, call }) => {
                state.agent.parent_id = Some(parent_id);
                state.agent.parent_call = Some(call);
            }
            _ => {}
        }
    }
}

// ============================================================================
// Links
// ============================================================================

#[derive(Clone)]
pub struct DatabricksLink;

impl DatabricksLink {
    fn trigger_call_opt(&self, calls: &[ToolCall]) -> Option<ToolCall> {
        let trigger = explore_databricks_tool_definition();
        calls.iter().find(|call| call.function.name == trigger.name).cloned()
    }
}

impl<ES: EventStore> Link<ES> for DatabricksLink {
    type AggregateA = AgentState<Planner>;
    type AggregateB = AgentState<DatabricksWorker>;

    async fn forward(
        &self,
        envelope: &Envelope<AgentState<Planner>>,
        _handler: &Handler<AgentState<Planner>, ES>,
    ) -> Option<(String, Command<DatabricksCommand>)> {
        if let Event::ToolCalls { calls } = &envelope.data
            && let Some(call) = self.trigger_call_opt(calls) {
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

    async fn backward(
        &self,
        envelope: &Envelope<AgentState<DatabricksWorker>>,
        _handler: &Handler<AgentState<DatabricksWorker>, ES>,
    ) -> Option<(String, Command<()>)> {
        use edda_agent::toolbox::ToolCallExt;
        if let Event::Agent(DatabricksEvent::Finished {
            parent_id,
            call,
            summary,
        }) = &envelope.data
        {
            let result = serde_json::to_value(summary).unwrap();
            let result = call.to_result(Ok(result));
            let command = Command::PutToolResults {
                results: vec![result],
            };
            return Some((parent_id.clone(), command));
        }
        None
    }
}

#[derive(Clone)]
pub struct CodingLink;

impl<ES: EventStore> Link<ES> for CodingLink {
    type AggregateA = AgentState<Planner>;
    type AggregateB = AgentState<CodingWorker>;

    async fn forward(
        &self,
        envelope: &Envelope<AgentState<Planner>>,
        _handler: &Handler<AgentState<Planner>, ES>,
    ) -> Option<(String, Command<CodingCommand>)> {
        if let Event::ToolCalls { calls } = &envelope.data
            && let Some(call) = calls.iter().find(|call| call.function.name == "send_coding_task") {
            let worker_id = format!("coding_{}", call.id);
            return Some((
                worker_id,
                Command::Agent(CodingCommand::Execute {
                    parent_id: envelope.aggregate_id.clone(),
                    call: call.clone(),
                }),
            ));
        }
        None
    }

    async fn backward(
        &self,
        envelope: &Envelope<AgentState<CodingWorker>>,
        _handler: &Handler<AgentState<CodingWorker>, ES>,
    ) -> Option<(String, Command<()>)> {
        use edda_agent::toolbox::ToolCallExt;
        if let Event::Agent(CodingEvent::Finished {
            parent_id,
            call,
            result,
        }) = &envelope.data
        {
            let result = serde_json::to_value(result).unwrap();
            let result = call.to_result(Ok(result));
            let command = Command::PutToolResults {
                results: vec![result],
            };
            return Some((parent_id.clone(), command));
        }
        None
    }
}

// ============================================================================
// Tool Definitions
// ============================================================================

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

fn send_coding_task_tool_definition() -> ToolDefinition {
    ToolDefinition {
        name: "send_coding_task".to_string(),
        description: "Send a Python coding task to a worker agent for execution".to_string(),
        parameters: serde_json::json!({
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "The coding task description for the worker"
                }
            },
            "required": ["description"]
        }),
    }
}

// ============================================================================
// Infrastructure
// ============================================================================

async fn store() -> PollingQueue<AnyStore> {
    let store = create_store(None).await.expect("Failed to create store");
    PollingQueue::new(store)
}

pub struct Validator;

impl toolbox::Validator for Validator {
    async fn run(
        &self,
        sandbox: &mut edda_sandbox::DaggerSandbox,
    ) -> Result<Result<(), String>> {
        use edda_sandbox::Sandbox;
        let result = sandbox.exec("uv run main.py").await?;
        if result.exit_code == 0 {
            sandbox.export_directory("/app", "/tmp/demo").await?;
            tracing::info!("App exported to /tmp/demo");
            Ok(Ok(()))
        } else {
            Ok(Err(format!(
                "code: {}\nstdout: {}\nstderr: {}",
                result.exit_code, result.stdout, result.stderr
            )))
        }
    }
}
