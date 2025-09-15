use crate::agent::{ToolWorker, Worker};
use crate::handler::Handler;
use crate::thread::{self, Thread};
use crate::toolbox::{self, basic::toolset};
use dabgent_mq::db::{EventStore, Metadata, Query};
use dabgent_sandbox::SandboxDyn;
use eyre;
use std::env;
use std::future::Future;
use std::pin::Pin;

const DEFAULT_SYSTEM_PROMPT: &str = "
You are a python software engineer.
Workspace is already set up using uv init.
Use uv package manager if you need to add extra libraries.
Program will be run using uv run main.py command.
You are also a planning expert who breaks down complex tasks to planning.md file and updates them there after each step.
";

pub struct PlannerValidator;

impl toolbox::Validator for PlannerValidator {
    async fn run(
        &self,
        sandbox: &mut Box<dyn SandboxDyn>,
    ) -> Result<Result<(), String>, eyre::Report> {
        let result = sandbox.exec("uv run main.py").await?;
        Ok(match result.exit_code {
            0 | 124 => Ok(()),
            code => Err(format!(
                "code: {}\nstdout: {}\nstderr: {}",
                code, result.stdout, result.stderr
            )),
        })
    }
}

pub struct PlanningAgent<S: EventStore> {
    store: S,
    planning_stream_id: String,
    planning_aggregate_id: String,
}

impl<S: EventStore> PlanningAgent<S> {
    pub fn new(store: S, base_stream_id: String, _base_aggregate_id: String) -> Self {
        Self {
            store,
            planning_stream_id: format!("{}_planning", base_stream_id),
            planning_aggregate_id: "thread".to_string(),
        }
    }

    pub async fn process_message(&self, content: String) -> eyre::Result<()> {
        self.store
            .push_event(
                &self.planning_stream_id,
                &self.planning_aggregate_id,
                &thread::Event::Prompted(content),
                &Metadata::default(),
            )
            .await?;
        Ok(())
    }

    pub async fn setup_workers(
        self,
        sandbox: Box<dyn SandboxDyn>,
        llm: rig::providers::anthropic::Client,
    ) -> eyre::Result<()> {
        let tools = toolset(PlannerValidator);
        let planning_worker = Worker::new(
            llm.clone(),
            self.store.clone(),
            "claude-sonnet-4-20250514".to_owned(),
            env::var("SYSTEM_PROMPT").unwrap_or_else(|_| DEFAULT_SYSTEM_PROMPT.to_owned()),
            tools.iter().map(|tool| tool.definition()).collect(),
        );
        let tools = toolset(PlannerValidator);
        let mut sandbox_worker = ToolWorker::new(sandbox, self.store.clone(), tools);
        let stream = self.planning_stream_id.clone();
        let aggregate = self.planning_aggregate_id.clone();
        tokio::spawn(async move {
            let _ = planning_worker.run(&stream, &aggregate).await;
        });
        let stream = self.planning_stream_id.clone();
        let aggregate = self.planning_aggregate_id.clone();
        tokio::spawn(async move {
            let _ = sandbox_worker.run(&stream, &aggregate).await;
        });
        Ok(())
    }

    pub async fn monitor_progress<F>(&self, mut on_status: F) -> eyre::Result<()>
    where
        F: FnMut(String) -> Pin<Box<dyn Future<Output = eyre::Result<()>> + Send>> + Send + 'static,
    {
        let mut receiver = self.store.subscribe::<thread::Event>(&Query {
            stream_id: self.planning_stream_id.clone(),
            event_type: None,
            aggregate_id: Some(self.planning_aggregate_id.clone()),
        })?;
        let mut events = self
            .store
            .load_events(
                &Query {
                    stream_id: self.planning_stream_id.clone(),
                    event_type: None,
                    aggregate_id: Some(self.planning_aggregate_id.clone()),
                },
                None,
            )
            .await?;
        let timeout = std::time::Duration::from_secs(300);
        loop {
            match tokio::time::timeout(timeout, receiver.next()).await {
                Ok(Some(Ok(event))) => {
                    events.push(event.clone());
                    let status = match &event {
                        thread::Event::Prompted(p) => format!("🎯 Starting task: {}", p),
                        thread::Event::LlmCompleted(_) => "🤔 Planning next steps...".to_string(),
                        thread::Event::ToolCompleted(_) => "🔧 Executing tools...".to_string(),
                    };
                    on_status(status).await?;
                    if matches!(Thread::fold(&events).state, thread::State::Done) {
                        on_status("✅ Task completed successfully!".to_string()).await?;
                        break;
                    }
                }
                Ok(Some(Err(e))) => {
                    on_status(format!("❌ Error: {}", e)).await?;
                    break;
                }
                Ok(None) => {
                    on_status("⚠️ Event stream closed".to_string()).await?;
                    break;
                }
                Err(_) => {
                    on_status("⏱️ Task timed out after 5 minutes".to_string()).await?;
                    break;
                }
            }
        }
        Ok(())
    }
}
