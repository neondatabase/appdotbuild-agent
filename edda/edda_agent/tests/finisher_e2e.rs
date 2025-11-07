mod common;

use common::{PythonValidator, create_test_store};
use edda_agent::llm::LLMProvider;
use edda_agent::processor::agent::{Agent, AgentState, Command, Event};
use edda_agent::processor::finish::FinishHandler;
use edda_agent::processor::link::Runtime;
use edda_agent::processor::llm::{LLMConfig, LLMHandler};
use edda_agent::processor::tools::{
    TemplateConfig, ToolHandler, get_dockerfile_dir_from_src_ws,
};
use edda_agent::processor::utils::LogHandler;
use edda_agent::toolbox::basic::toolset;
use edda_mq::Event as MQEvent;
use edda_sandbox::SandboxHandle;
use eyre::Result;
use rig::message::ToolResult;
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tempfile::TempDir;

const SYSTEM_PROMPT: &str = "
You are a python software engineer.
Workspace is already set up using uv init.
Use uv package manager if you need to add extra libraries.
Program will be run using uv run main.py command.
When you finish the task, call the done tool to signal completion.
";

const USER_PROMPT: &str =
    "Write a minimal Python script that prints 'Hello from Finisher E2E Test!'";

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

impl Basic {
    fn is_success(&self, result: &ToolResult) -> bool {
        result.content.iter().any(|c| match c {
            rig::message::ToolResultContent::Text(text) => text.text.contains("success"),
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

impl Agent for Basic {
    const TYPE: &'static str = "finisher_e2e_test";
    type AgentCommand = ();
    type AgentEvent = BasicEvent;
    type AgentError = BasicError;
    type Services = ();

    async fn handle(
        state: &AgentState<Self>,
        cmd: Command<Self::AgentCommand>,
        services: &Self::Services,
    ) -> Result<Vec<Event<Self::AgentEvent>>, edda_agent::processor::agent::AgentError<Self::AgentError>> {
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
            _ => state.apply_shared(event),
        }
    }
}

#[tokio::test]
#[cfg_attr(not(feature = "dagger"), ignore)]
async fn test_finisher_e2e_with_real_dagger() -> Result<()> {
    dotenvy::dotenv().ok();

    let llm_provider = LLMProvider::Anthropic;
    // Skip test if no LLM API key available
    let llm_client = match llm_provider.client_from_env().map(Into::into) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("Skipping test_finisher_e2e_with_real_dagger: {e}");
            return Ok(());
        }
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
            model: llm_provider.default_model().to_string(),
            preamble: Some(SYSTEM_PROMPT.to_string()),
            tools: Some(tools.iter().map(|tool| tool.definition()).collect()),
            ..Default::default()
        },
    );

    // Setup sandbox and template
    let sandbox_handle = SandboxHandle::new(Default::default());
    let template_config = TemplateConfig::default_dir(get_dockerfile_dir_from_src_ws());

    // Setup tool handler
    let tool_handler = ToolHandler::new(tools, sandbox_handle.clone(), template_config.clone());

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
    runtime
        .handler
        .execute("finisher-e2e-test", command)
        .await?;

    // Run runtime in background (it will run forever, we just need artifacts to be exported)
    let _runtime_handle = tokio::spawn(async move { runtime.start().await });

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
