mod common;

use common::{create_test_store, PythonValidator};
use dabgent_agent::processor::agent::{Agent, AgentState, Command, Event};
use dabgent_agent::processor::finish::FinishHandler;
use dabgent_agent::processor::link::Runtime;
use dabgent_agent::processor::llm::{LLMConfig, LLMHandler};
use dabgent_agent::processor::tools::{TemplateConfig, ToolHandler};
use dabgent_agent::processor::utils::LogHandler;
use dabgent_agent::toolbox::basic::toolset;
use dabgent_mq::Event as MQEvent;
use dabgent_sandbox::SandboxHandle;
use eyre::Result;
use rig::client::ProviderClient;
use rig::message::ToolResult;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::Duration;
use tempfile::TempDir;

const MODEL: &str = "claude-sonnet-4-20250514";

const SYSTEM_PROMPT: &str = "
You are a python software engineer.
Workspace is already set up using uv init.
Use uv package manager if you need to add extra libraries.
Program will be run using uv run main.py command.
When you finish the task, call the done tool to signal completion.
";

const USER_PROMPT: &str = "Write a minimal Python script that prints 'Hello from Finisher E2E Test!'";

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Basic {
    pub done_call_id: Option<String>,
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
    const TYPE: &'static str = "finisher_e2e_test";
    type AgentCommand = ();
    type AgentEvent = BasicEvent;
    type AgentError = BasicError;
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
                    rig::message::ToolResultContent::Text(text) => text.text.contains("success"),
                    _ => false,
                });
                if is_done {
                    return Ok(vec![Event::Agent(BasicEvent::Finished)]);
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

fn get_llm_client() -> Option<Arc<rig::providers::anthropic::Client>> {
    if std::env::var("ANTHROPIC_API_KEY").is_ok() {
        Some(Arc::new(rig::providers::anthropic::Client::from_env()))
    } else {
        None
    }
}

#[tokio::test]
async fn test_finisher_e2e_with_real_dagger() -> Result<()> {
    dotenvy::dotenv().ok();

    // Skip test if no LLM API key available
    let Some(llm_client) = get_llm_client() else {
        eprintln!("Skipping test_finisher_e2e_with_real_dagger: No ANTHROPIC_API_KEY set");
        return Ok(());
    };

    tracing_subscriber::fmt::init();

    // Create temporary directory for artifact export
    let temp_dir = TempDir::new()?;
    let export_path = temp_dir.path().to_string_lossy().to_string();

    println!("Export path: {}", export_path);

    // Setup store and tools
    let store = create_test_store().await;
    let tools = toolset(PythonValidator);
    let tools_for_finish = toolset(PythonValidator);

    // Setup LLM handler
    let llm = LLMHandler::new(
        llm_client,
        LLMConfig {
            model: MODEL.to_string(),
            preamble: Some(SYSTEM_PROMPT.to_string()),
            tools: Some(tools.iter().map(|tool| tool.definition()).collect()),
            ..Default::default()
        },
    );

    // Setup sandbox and template
    let sandbox_handle = SandboxHandle::new(Default::default());

    // Find the examples directory relative to the test
    let manifest_dir = std::env::var("CARGO_MANIFEST_DIR")?;
    let examples_dir = std::path::Path::new(&manifest_dir).join("examples");
    let template_config = TemplateConfig::default_dir(examples_dir.to_str().unwrap());

    // Setup tool handler
    let tool_handler = ToolHandler::new(
        tools,
        sandbox_handle.clone(),
        template_config.clone(),
    );

    // Setup finish handler
    let finish_handler = FinishHandler::new(
        sandbox_handle,
        export_path.clone(),
        tools_for_finish,
        template_config,
    );

    // Create runtime with all handlers
    let runtime = Runtime::<AgentState<Basic>, _>::new(store, ())
        .with_handler(llm)
        .with_handler(tool_handler)
        .with_handler(finish_handler)
        .with_handler(LogHandler);

    // Execute agent with test prompt
    let command = Command::PutUserMessage {
        content: rig::OneOrMany::one(rig::message::UserContent::text(USER_PROMPT)),
    };
    runtime.handler.execute("finisher-e2e-test", command).await?;

    // Run runtime in background (it will run forever, we just need artifacts to be exported)
    let _runtime_handle = tokio::spawn(async move {
        runtime.start().await
    });

    // Give it time to complete the task and export artifacts
    // The agent typically finishes in 15-30 seconds, export takes ~1 second
    tokio::time::sleep(Duration::from_secs(60)).await;

    // Verify artifacts were exported
    let main_py_path = temp_dir.path().join("main.py");
    assert!(
        main_py_path.exists(),
        "main.py should be exported to {}",
        main_py_path.display()
    );

    // Verify content
    let content = std::fs::read_to_string(&main_py_path)?;
    println!("Exported main.py content:\n{}", content);

    assert!(
        content.contains("Hello from Finisher E2E Test") || content.contains("hello"),
        "main.py should contain the expected greeting"
    );

    // Verify .gitignore patterns are respected (no __pycache__ etc.)
    let pycache_path = temp_dir.path().join("__pycache__");
    assert!(
        !pycache_path.exists(),
        "__pycache__ should not be exported due to .gitignore"
    );

    // List all exported files for debugging
    println!("Exported files:");
    for entry in std::fs::read_dir(temp_dir.path())? {
        let entry = entry?;
        println!("  - {}", entry.path().display());
    }

    Ok(())
}
