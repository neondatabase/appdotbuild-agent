use dabgent_agent::processor::{Pipeline, Processor, ThreadProcessor, ToolProcessor};
use dabgent_agent::toolbox::{self, basic::toolset, planning::planning_toolset};
use dabgent_mq::EventStore;
use dabgent_mq::db::sqlite::SqliteStore;
use dabgent_sandbox::dagger::{ConnectOpts, Sandbox as DaggerSandbox};
use dabgent_sandbox::{NoOpSandbox, Sandbox, SandboxDyn};
use eyre::Result;
use rig::client::ProviderClient;

const MODEL: &str = "claude-sonnet-4-20250514";

const SYSTEM_PROMPT: &str = "
You are a python software engineer.
Workspace is already set up using uv init.
Use uv package manager if you need to add extra libraries.
Program will be run using uv run main.py command.
";

const PLANNING_PROMPT: &str = "
You are a planning assistant that breaks down complex tasks into actionable steps.

Create a clear, actionable plan that an engineer can follow.

When creating a plan:
1. Break down the task into clear, specific steps
2. Each step should be a concrete action
3. Order the steps logically
4. Use the create_plan tool to submit your plan

The create_plan tool expects an array of task descriptions.
Each task should be a concrete, actionable step that can be independently executed.
";

#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt::init();

    const STREAM_ID: &str = "planning-pipeline";
    let prompt = "Create a hello world Python script that prints a greeting";

    let store = store().await;

    // Run the planning and execution pipeline
    planning_pipeline(STREAM_ID, store, prompt)
        .await
        .expect("Pipeline failed");
}

pub async fn planning_pipeline(
    stream_id: &str,
    store: impl EventStore + Clone,
    task: &str,
) -> Result<()> {
    let stream_id = stream_id.to_owned();
    let task = task.to_owned();

    let opts = ConnectOpts::default();
    opts.connect(|client| async move {

        let llm = rig::providers::anthropic::Client::from_env();

        // Phase 1: Planning

        let planning_config = dabgent_agent::event::Event::LLMConfig {
            model: MODEL.to_string(),
            temperature: 0.7,
            max_tokens: 4096,
            preamble: Some(PLANNING_PROMPT.to_string()),
            tools: Some(
                planning_toolset(store.clone(), stream_id.clone())
                    .iter()
                    .map(|tool| tool.definition())
                    .collect()
            ),
            recipient: Some("planner".to_string()),
            parent: None,
        };
        store
            .push_event(&stream_id, "planner", &planning_config, &Default::default())
            .await?;

        let user_message = dabgent_agent::event::Event::UserMessage(
            rig::OneOrMany::one(rig::message::UserContent::Text(rig::message::Text {
                text: format!("Please create a plan for the following task: {}", task),
            }))
        );
        store
            .push_event(&stream_id, "planner", &user_message, &Default::default())
            .await?;

        let planning_sandbox = NoOpSandbox::new();
        let planning_tools = planning_toolset(store.clone(), stream_id.clone());

        let planning_thread = ThreadProcessor::new(llm.clone(), store.clone());
        let planning_tool_processor = ToolProcessor::new(
            planning_sandbox.boxed(),
            store.clone(),
            planning_tools,
            Some("planner".to_string()),
        );

        let planning_completion_processor = dabgent_agent::processor::CompletionProcessor::new(store.clone());
        let planning_pipeline = Pipeline::new(
            store.clone(),
            vec![planning_thread.boxed(), planning_tool_processor.boxed(), planning_completion_processor.boxed()],
        );

        let pipeline_handle = tokio::spawn({
            let stream_id = stream_id.clone();
            async move {
                planning_pipeline.run(stream_id).await
            }
        });

        // Wait for PlanCreated event
        let mut plan_created = false;
        while !plan_created {
            tokio::time::sleep(tokio::time::Duration::from_millis(500)).await;

            let query = dabgent_mq::Query::stream(&stream_id).aggregate("planner");
            let events = store.load_events::<dabgent_agent::event::Event>(&query, None).await?;

            for event in events.iter() {
                if matches!(event, dabgent_agent::event::Event::PlanCreated { .. }) {
                    plan_created = true;
                    break;
                }
            }
        }

        // Stop the planning pipeline
        pipeline_handle.abort();

        // Phase 2: Execution

        let query = dabgent_mq::Query::stream(&stream_id).aggregate("planner");
        let events = store.load_events::<dabgent_agent::event::Event>(&query, None).await?;

        let mut plan_tasks: Option<Vec<String>> = None;
        for event in events.iter() {
            match event {
                dabgent_agent::event::Event::PlanCreated { tasks } |
                dabgent_agent::event::Event::PlanUpdated { tasks } => {
                    plan_tasks = Some(tasks.clone());
                }
                _ => {}
            }
        }

        if let Some(tasks) = plan_tasks {

            let execution_sandbox = sandbox(&client).await?;
            let execution_tools = toolset(Validator);

            let execution_thread = ThreadProcessor::new(llm.clone(), store.clone());
            let execution_tool_processor = ToolProcessor::new(
                execution_sandbox.boxed(),
                store.clone(),
                execution_tools,
                None,
            );

            let execution_completion_processor = dabgent_agent::processor::CompletionProcessor::new(store.clone());
            let execution_pipeline = Pipeline::new(
                store.clone(),
                vec![execution_thread.boxed(), execution_tool_processor.boxed(), execution_completion_processor.boxed()],
            );

            let exec_handle = tokio::spawn({
                let stream_id = stream_id.clone();
                async move {
                    execution_pipeline.run(stream_id).await
                }
            });

            for (i, task_desc) in tasks.iter().enumerate() {
                let thread_id = format!("task-{}", i);

                let worker_config = dabgent_agent::event::Event::LLMConfig {
                    model: MODEL.to_string(),
                    temperature: 0.7,
                    max_tokens: 4096,
                    preamble: Some(SYSTEM_PROMPT.to_string()),
                    tools: Some(
                        toolset(Validator)
                            .iter()
                            .map(|tool| tool.definition())
                            .collect()
                    ),
                    recipient: None,
                    parent: None,
                };
                store
                    .push_event(&stream_id, &thread_id, &worker_config, &Default::default())
                    .await?;

                let task_message = dabgent_agent::event::Event::UserMessage(
                    rig::OneOrMany::one(rig::message::UserContent::Text(rig::message::Text {
                        text: format!("{}\nWhen complete, call the 'done' tool to mark this task as finished.", task_desc),
                    }))
                );
                store
                    .push_event(&stream_id, &thread_id, &task_message, &Default::default())
                    .await?;

                // Wait for task completion
                loop {
                    tokio::time::sleep(tokio::time::Duration::from_millis(500)).await;

                    let query = dabgent_mq::Query::stream(&stream_id);
                    let events = store.load_events::<dabgent_agent::event::Event>(&query, None).await?;

                    let completed_count = events.iter()
                        .filter(|e| matches!(e, dabgent_agent::event::Event::TaskCompleted { .. }))
                        .count();

                    if completed_count > i {
                        break;
                    }
                }
            }

            exec_handle.abort();

        }

        Ok(())
    })
    .await
    .map_err(Into::into)
}

async fn sandbox(client: &dagger_sdk::DaggerConn) -> Result<DaggerSandbox> {
    let opts = dagger_sdk::ContainerBuildOptsBuilder::default()
        .dockerfile("Dockerfile")
        .build()?;
    let ctr = client
        .container()
        .build_opts(client.host().directory("./examples"), opts);
    ctr.sync().await?;
    let sandbox = DaggerSandbox::from_container(ctr, client.clone());
    Ok(sandbox)
}

async fn store() -> SqliteStore {
    let pool = sqlx::SqlitePool::connect(":memory:")
        .await
        .expect("Failed to create in-memory SQLite pool");
    let store = SqliteStore::new(pool);
    store.migrate().await;
    store
}

pub struct Validator;

impl toolbox::Validator for Validator {
    async fn run(&self, sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
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