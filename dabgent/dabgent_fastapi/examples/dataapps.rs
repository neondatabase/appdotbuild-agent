use dabgent_agent::processor::agent::{Agent, AgentState, Command, Event};
use dabgent_agent::processor::link::Runtime;
use dabgent_agent::processor::finish::FinishHandler;
use dabgent_agent::processor::llm::{LLMConfig, LLMHandler};
use dabgent_agent::processor::tools::{TemplateConfig, ToolHandler};
use dabgent_agent::processor::utils::{LogHandler, ShutdownHandler};
use dabgent_fastapi::{toolset::dataapps_toolset, validator::DataAppsValidator};
use dabgent_mq::listener::PollingQueue;
use dabgent_mq::{create_store, Event as MQEvent, StoreConfig};
use dabgent_sandbox::SandboxHandle;
use eyre::Result;
use rig::client::ProviderClient;
use rig::message::{ToolResult, ToolResultContent};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::oneshot;


#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .init();
    run_worker().await.unwrap();
}

pub async fn run_worker() -> Result<()> {
    let store = create_store(Some(StoreConfig::from_env())).await?;
    let store = PollingQueue::new(store);

    let tools = dataapps_toolset(DataAppsValidator::new());

    let sandbox_handle = SandboxHandle::new(Default::default());
    let template_config = TemplateConfig::new("./dabgent_fastapi".to_string(), "fastapi.Dockerfile".to_string())
        .with_template("../dataapps/template_minimal".to_string());

    let llm = LLMHandler::new(
        Arc::new(rig::providers::gemini::Client::from_env()),
        LLMConfig {
            model: MODEL.to_string(),
            preamble: Some(SYSTEM_PROMPT.to_string()),
            tools: Some(tools.iter().map(|tool| tool.definition()).collect()),
            ..Default::default()
        },
    );

    let tool_handler = ToolHandler::new(
        tools,
        sandbox_handle.clone(),
        template_config.clone(),
    );

    let mut runtime = Runtime::<AgentState<DataAppsAgent>, _>::new(store, ())
        .with_handler(llm)
        .with_handler(tool_handler);

    // Wipe and prepare export path
    let export_path = "/tmp/data_app";
    if std::path::Path::new(export_path).exists() {
        std::fs::remove_dir_all(export_path)?;
    }

    let tools_for_finish = dataapps_toolset(DataAppsValidator::new());
    let finish_handler = FinishHandler::new(
        sandbox_handle,
        export_path.to_string(),
        tools_for_finish,
        template_config,
    );
    runtime = runtime.with_handler(finish_handler);

    // Setup shutdown handler to trigger on Shutdown event
    let (shutdown_tx, shutdown_rx) = oneshot::channel();
    let shutdown_handler = ShutdownHandler::new(shutdown_tx);
    runtime = runtime.with_handler(shutdown_handler);

    let runtime = runtime.with_handler(LogHandler);

    // Send initial command before starting runtime
    let command = Command::PutUserMessage {
        content: rig::OneOrMany::one(rig::message::UserContent::text(USER_PROMPT)),
    };
    runtime.handler.execute("dataapps", command).await?;

    // Run pipeline with graceful shutdown on completion
    tokio::select! {
        result = runtime.start() => {
            result
        },
        _ = shutdown_rx => {
            tracing::info!("Graceful shutdown triggered");
            Ok(())
        }
    }
}

const SYSTEM_PROMPT: &str = "
You are a FastAPI and React developer creating data applications.

Workspace Setup:
- You have a pre-configured DataApps project structure in /app with backend and frontend directories
- Backend is in /app/backend with Python, FastAPI, and uv package management
- Frontend is in /app/frontend with React Admin and TypeScript
- Use 'uv run' for all Python commands (e.g., 'uv run python main.py')

Your Task:
1. Create a simple data API with one endpoint that returns sample data
2. Configure React Admin UI to display this data in a table
3. Add proper logging and debugging throughout
4. Ensure CORS is properly configured for React Admin

Implementation Details:
- Add /api/items endpoint in backend/main.py that returns a list of sample items
- Each item should have: id, name, description, category, created_at fields
- Update frontend/src/App.tsx to add a Resource for items with ListGuesser
- Include X-Total-Count header for React Admin pagination
- Add debug logging in both backend (print/logging) and frontend (console.log)

Quality Requirements:
- Follow React Admin patterns for data providers
- Use proper REST API conventions (/api/resource)
- Handle errors gracefully with clear messages
- Run all linters and tests before completion

Start by exploring the current project structure, then implement the required features.
Use the tools available to you as needed.
";

const USER_PROMPT: &str = "
Create a simple DataApp with:

1. Backend API endpoint `/api/items` that returns a list of sample items (each item should have id, name, description, category, created_at fields)
2. React Admin frontend that displays these items in a table with proper columns
3. Include debug logging in both backend and frontend
4. Make sure the React Admin data provider can fetch and display the items

The app should be functional.
";

const MODEL: &str = "gemini-2.5-flash";

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DataAppsAgent {
    pub done_call_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum DataAppsEvent {
    Finished,
}

impl MQEvent for DataAppsEvent {
    fn event_type(&self) -> String {
        match self {
            DataAppsEvent::Finished => "finished".to_string(),
        }
    }

    fn event_version(&self) -> String {
        "1.0".to_string()
    }
}

#[derive(Debug)]
pub enum DataAppsError {}

impl std::fmt::Display for DataAppsError {
    fn fmt(&self, _f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        Ok(())
    }
}

impl std::error::Error for DataAppsError {}

impl Agent for DataAppsAgent {
    const TYPE: &'static str = "dataapps_worker";
    type AgentCommand = ();
    type AgentEvent = DataAppsEvent;
    type AgentError = DataAppsError;
    type Services = ();

    async fn handle_tool_results(
        state: &AgentState<Self>,
        _: &Self::Services,
        incoming: Vec<ToolResult>,
    ) -> Result<Vec<Event<Self::AgentEvent>>, Self::AgentError> {
        let completed = state.merge_tool_results(&incoming);
        if let Some(done_id) = &state.agent.done_call_id {
            if let Some(result) = completed.iter().find(|r| done_id == &r.id) {
                let is_done = result.content.iter().any(|c| match c {
                    ToolResultContent::Text(text) => text.text.contains("success"),
                    _ => false,
                });
                if is_done {
                    return Ok(vec![Event::Agent(DataAppsEvent::Finished)]);
                }
            }
        }
        Ok(vec![state.results_passthrough(&incoming)])
    }

    fn apply_event(state: &mut AgentState<Self>, event: Event<Self::AgentEvent>) {
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

