mod common;

use common::{PythonValidator, create_test_store};
use edda_agent::llm::{LLMClient, LLMProvider, WithRetryExt};
use edda_agent::processor::agent::{Agent, AgentState, Command, Event};
use edda_agent::processor::link::Runtime;
use edda_agent::processor::llm::{LLMConfig, LLMHandler};
use edda_agent::processor::tools::{
    TemplateConfig, ToolHandler, get_dockerfile_dir_from_src_ws,
};
use edda_agent::toolbox::basic::toolset;
use edda_mq::{Event as MQEvent, EventStore};
use edda_sandbox::SandboxHandle;
use eyre::Result;
use rig::message::{ToolResult, ToolResultContent};
use serde::{Deserialize, Serialize};
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

impl BasicAgent {
    fn is_success(&self, result: &ToolResult) -> bool {
        result.content.iter().any(|c| match c {
            ToolResultContent::Text(text) => text.text.contains("success"),
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

impl Agent for BasicAgent {
    const TYPE: &'static str = "e2e_basic_worker";
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

/// Test with Anthropic (Claude)
#[tokio::test]
#[cfg_attr(not(feature = "dagger"), ignore)]
async fn test_e2e_basic_anthropic() {
    test_e2e_basic_impl(
        "test_e2e_basic_anthropic",
        LLMProvider::Anthropic,
        "anthropic_basic",
    )
    .await
}

async fn test_e2e_basic_impl(test_name: &str, llm_provider: LLMProvider, aggregate_id: &str) {
    dotenvy::dotenv().ok();
    if !llm_provider.is_api_key_env_var_set() {
        eprintln!(
            "Skipping {test_name}: env var {} not set",
            llm_provider.api_key_env_var()
        );
        return;
    }

    let result = timeout(
        Duration::from_secs(180),
        run_basic_workflow(llm_provider, aggregate_id),
    )
    .await;

    match result {
        Ok(Ok(())) => eprintln!(
            "✓ E2E test completed successfully with {}",
            llm_provider.name()
        ),
        Ok(Err(e)) => panic!("E2E test failed: {}", e),
        Err(_) => panic!("E2E test timed out after 180 seconds"),
    }
}

async fn run_basic_workflow(llm_provider: LLMProvider, aggregate_id: &str) -> Result<()> {
    let store = create_test_store().await;
    let tools = toolset(PythonValidator);

    let system_prompt = "
You are a python software engineer.
Workspace is already set up using uv init.
Use uv package manager if you need to add extra libraries.
Program will be run using uv run main.py command.
IMPORTANT: After the script runs successfully, you MUST call the 'done' tool to complete the task.
";

    let user_prompt =
        "write a simple python script that prints 'Hello World!' and the result of 1+1";

    let llm = LLMHandler::new(
        llm_provider.client_from_env_raw().with_retry().into_arc(),
        LLMConfig {
            model: llm_provider.default_model().to_string(),
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

    let runtime = Runtime::<AgentState<BasicAgent>, _>::new(store.clone(), ())
        .with_handler(llm)
        .with_handler(tool_handler);

    let command = Command::PutUserMessage {
        content: rig::OneOrMany::one(rig::message::UserContent::text(user_prompt)),
    };
    runtime.handler.execute(aggregate_id, command).await?;

    // Start the runtime in the background
    let runtime_handle = tokio::spawn(async move { runtime.start().await });

    // Poll for the Finished event
    let mut interval = tokio::time::interval(Duration::from_millis(500));
    let start = tokio::time::Instant::now();
    let max_wait = Duration::from_secs(150);

    loop {
        interval.tick().await;

        // Check if we've timed out
        if start.elapsed() > max_wait {
            return Err(eyre::eyre!(
                "Workflow did not complete within {} seconds",
                max_wait.as_secs()
            ));
        }

        // Load events and check for Finished
        let events = store
            .load_events::<AgentState<BasicAgent>>(aggregate_id)
            .await?;

        let finished = events
            .iter()
            .any(|e| matches!(e.data, Event::Agent(BasicEvent::Finished)));

        if finished {
            eprintln!("✓ Workflow completed - Finished event detected");
            runtime_handle.abort();
            return Ok(());
        }

        // Check if runtime has crashed
        if runtime_handle.is_finished() {
            let result = runtime_handle.await.expect("runtime task panicked");
            return Err(eyre::eyre!("Runtime terminated unexpectedly: {:?}", result));
        }
    }
}
