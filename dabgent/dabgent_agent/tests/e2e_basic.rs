mod common;

use common::{create_test_store, PythonValidator};
use dabgent_agent::llm::{LLMClientDyn, WithRetryExt};
use dabgent_agent::processor::agent::{Agent, AgentState, Command, Event, Request, Runtime};
use dabgent_agent::processor::llm::{LLMConfig, LLMHandler};
use dabgent_agent::processor::tools::{
    get_dockerfile_dir_from_src_ws, TemplateConfig, ToolHandler,
};
use dabgent_agent::toolbox::basic::toolset;
use dabgent_mq::{Event as MQEvent, EventStore};
use dabgent_sandbox::SandboxHandle;
use eyre::Result;
use rig::client::ProviderClient;
use rig::message::{ToolResult, ToolResultContent, UserContent};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::Duration;
use tokio::time::timeout;

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct BasicAgent {
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

impl Agent for BasicAgent {
    const TYPE: &'static str = "e2e_basic_worker";
    type AgentCommand = ();
    type AgentEvent = BasicEvent;
    type AgentError = BasicError;
    type Services = ();

    async fn handle_tool_results(
        state: &AgentState<Self>,
        _: &Self::Services,
        incoming: Vec<ToolResult>,
    ) -> Result<Vec<Event<Self::AgentEvent>>, Self::AgentError> {
        let completed = state.merge_tool_results(incoming);
        if let Some(done_id) = &state.agent.done_call_id {
            if let Some(result) = completed.iter().find(|r| done_id == &r.id) {
                let is_done = result.content.iter().any(|c| match c {
                    ToolResultContent::Text(text) => text.text.contains("success"),
                    _ => false,
                });
                if is_done {
                    return Ok(vec![Event::Agent(BasicEvent::Finished)]);
                }
            }
        }
        let content = completed.into_iter().map(UserContent::ToolResult);
        let content = rig::OneOrMany::many(content).unwrap();
        Ok(vec![Event::Request(Request::Completion { content })])
    }

    fn apply_event(state: &mut AgentState<Self>, event: Event<Self::AgentEvent>) {
        match event {
            Event::Request(Request::ToolCalls { ref calls }) => {
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

/// Test with Anthropic (Claude)
#[tokio::test]
async fn test_e2e_basic_anthropic() {
    dotenvy::dotenv().ok();
    if std::env::var("ANTHROPIC_API_KEY").is_err() {
        eprintln!("Skipping test_e2e_basic_anthropic: ANTHROPIC_API_KEY not set");
        return;
    }

    let result = timeout(Duration::from_secs(180), run_basic_workflow(
        "claude-sonnet-4-5-20250929",
        Arc::new(rig::providers::anthropic::Client::from_env().with_retry()),
        "anthropic_basic",
    )).await;

    match result {
        Ok(Ok(())) => eprintln!("✓ E2E test completed successfully with Anthropic"),
        Ok(Err(e)) => panic!("E2E test failed: {}", e),
        Err(_) => panic!("E2E test timed out after 180 seconds"),
    }
}

/// Test with OpenRouter (DeepSeek)
#[tokio::test]
async fn test_e2e_basic_openrouter() {
    dotenvy::dotenv().ok();
    if std::env::var("OPENROUTER_API_KEY").is_err() {
        eprintln!("Skipping test_e2e_basic_openrouter: OPENROUTER_API_KEY not set");
        return;
    }

    let result = timeout(Duration::from_secs(180), run_basic_workflow(
        "deepseek/deepseek-v3.2-exp",
        Arc::new(rig::providers::openrouter::Client::from_env().with_retry()),
        "openrouter_basic",
    )).await;

    match result {
        Ok(Ok(())) => eprintln!("✓ E2E test completed successfully with OpenRouter"),
        Ok(Err(e)) => panic!("E2E test failed: {}", e),
        Err(_) => panic!("E2E test timed out after 180 seconds"),
    }
}

async fn run_basic_workflow(
    model: &str,
    client: Arc<dyn LLMClientDyn>,
    aggregate_id: &str,
) -> Result<()> {
    let store = create_test_store().await;
    let tools = toolset(PythonValidator);

    let system_prompt = "
You are a python software engineer.
Workspace is already set up using uv init.
Use uv package manager if you need to add extra libraries.
Program will be run using uv run main.py command.
IMPORTANT: After the script runs successfully, you MUST call the 'done' tool to complete the task.
";

    let user_prompt = "write a simple python script that prints 'Hello World!' and the result of 1+1";

    let llm = LLMHandler::new(
        client,
        LLMConfig {
            model: model.to_string(),
            preamble: Some(system_prompt.to_string()),
            tools: Some(tools.iter().map(|tool| tool.definition()).collect()),
            ..Default::default()
        },
    );

    let tool_handler = ToolHandler::new(
        tools,
        SandboxHandle::new(Default::default()),
        TemplateConfig::default_dir(get_dockerfile_dir_from_src_ws()),
    );

    let runtime = Runtime::<BasicAgent, _>::new(store.clone(), ())
        .with_handler(llm)
        .with_handler(tool_handler);

    let command = Command::SendRequest(Request::Completion {
        content: rig::OneOrMany::one(rig::message::UserContent::text(user_prompt)),
    });
    runtime.handler.execute(aggregate_id, command).await?;

    // Start the runtime in the background
    let runtime_handle = tokio::spawn(async move {
        runtime.start().await
    });

    // Poll for the Finished event
    let mut interval = tokio::time::interval(Duration::from_millis(500));
    let start = tokio::time::Instant::now();
    let max_wait = Duration::from_secs(150);

    loop {
        interval.tick().await;

        // Check if we've timed out
        if start.elapsed() > max_wait {
            return Err(eyre::eyre!("Workflow did not complete within {} seconds", max_wait.as_secs()));
        }

        // Load events and check for Finished
        let events = store.load_events::<AgentState<BasicAgent>>(aggregate_id).await?;

        let finished = events.iter().any(|e| matches!(e.data, Event::Agent(BasicEvent::Finished)));

        if finished {
            eprintln!("✓ Workflow completed - Finished event detected");
            runtime_handle.abort();
            return Ok(());
        }

        // Check if runtime has crashed
        if runtime_handle.is_finished() {
            return Err(eyre::eyre!("Runtime terminated unexpectedly"));
        }
    }
}
