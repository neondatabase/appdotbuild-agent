use dabgent_agent::processor::{FinishProcessor, Pipeline, Processor, ThreadProcessor, ToolProcessor};
use dabgent_agent::toolbox::ToolDyn;
use dabgent_fastapi::{toolset::dataapps_toolset, validator::DataAppsValidator, artifact_preparer::DataAppsArtifactPreparer};
use dabgent_mq::{EventStore, create_store, StoreConfig};
use dabgent_sandbox::dagger::{ConnectOpts, Sandbox as DaggerSandbox};
use dabgent_sandbox::SandboxFork;
use eyre::Result;
use rig::client::ProviderClient;


#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .init();

    const STREAM_ID: &str = "dataapps";
    const AGGREGATE_ID: &str = "thread";

    let opts = ConnectOpts::default();
    opts.connect(|client| async move {
        let llm = rig::providers::gemini::Client::from_env();
        let store = create_store(Some(StoreConfig::from_env())).await?;
        tracing::info!("Event store initialized successfully");
        let sandbox = create_sandbox(&client).await?;
        let tool_processor_tools = dataapps_toolset(DataAppsValidator::new());
        let finish_processor_tools = dataapps_toolset(DataAppsValidator::new());

        push_llm_config(&store, STREAM_ID, AGGREGATE_ID, &tool_processor_tools).await?;
        push_seed_sandbox_from_template(&store, STREAM_ID, AGGREGATE_ID, "../dataapps/template_minimal", "/app").await?;
        push_prompt(&store, STREAM_ID, AGGREGATE_ID, USER_PROMPT).await?;

        tracing::info!("Starting DataApps pipeline with model: {}", MODEL);

        let thread_processor = ThreadProcessor::new(llm.clone(), store.clone());

        // Create export directory path with timestamp
        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let export_path = format!("/tmp/dataapps_output_{}", timestamp);

        // Fork sandbox for completion processor
        let completion_sandbox = sandbox.fork().await?;
        let tool_processor = ToolProcessor::new(dabgent_sandbox::Sandbox::boxed(sandbox), store.clone(), tool_processor_tools, None);

        // FixMe: FinishProcessor should have no state, including export path
        let finish_processor = FinishProcessor::new_with_preparer(
            dabgent_sandbox::Sandbox::boxed(completion_sandbox),
            store.clone(),
            export_path.clone(),
            finish_processor_tools,
            DataAppsArtifactPreparer,
        );

        let pipeline = Pipeline::new(
            store.clone(),
            vec![
                thread_processor.boxed(),
                tool_processor.boxed(),
                finish_processor.boxed(),
            ],
        );

        tracing::info!("Artifacts will be exported to: {}", export_path);

        tracing::info!("Pipeline configured, starting execution...");

        pipeline.run(STREAM_ID.to_owned()).await?;
        Ok(())
    })
    .await
    .unwrap();
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

async fn create_sandbox(client: &dagger_sdk::DaggerConn) -> Result<DaggerSandbox> {
    tracing::info!("Setting up sandbox with DataApps template...");

    // Build container from fastapi.Dockerfile
    let opts = dagger_sdk::ContainerBuildOptsBuilder::default()
        .dockerfile("fastapi.Dockerfile")
        .build()?;

    let ctr = client
        .container()
        .build_opts(client.host().directory("./dabgent_fastapi"), opts);

    ctr.sync().await?;
    let sandbox = DaggerSandbox::from_container(ctr, client.clone());
    tracing::info!("Sandbox ready for DataApps development");
    Ok(sandbox)
}

async fn push_llm_config<S: EventStore>(
    store: &S,
    stream_id: &str,
    aggregate_id: &str,
    tools: &[Box<dyn ToolDyn>],
) -> Result<()> {
    tracing::info!("Pushing LLM configuration to event store...");

    // Extract tool definitions from the tools
    let tool_definitions: Vec<rig::completion::ToolDefinition> = tools
        .iter()
        .map(|tool| tool.definition())
        .collect();

    let event = dabgent_agent::event::Event::LLMConfig {
        model: MODEL.to_owned(),
        temperature: 0.0,
        max_tokens: 8192,
        preamble: Some(SYSTEM_PROMPT.to_owned()),
        tools: Some(tool_definitions),
        recipient: None,
    };
    store
        .push_event(stream_id, aggregate_id, &event, &Default::default())
        .await
        .map_err(Into::into)
}

async fn push_seed_sandbox_from_template<S: EventStore>(
    store: &S,
    stream_id: &str,
    aggregate_id: &str,
    template_path: &str,
    base_path: &str,
) -> Result<()> {
    tracing::info!("Pushing seed sandbox event to event store...");
    let event = dabgent_agent::event::Event::SeedSandboxFromTemplate {
        template_path: template_path.to_owned(),
        base_path: base_path.to_owned(),
    };
    store
        .push_event(stream_id, aggregate_id, &event, &Default::default())
        .await
        .map_err(Into::into)
}

async fn push_prompt<S: EventStore>(
    store: &S,
    stream_id: &str,
    aggregate_id: &str,
    prompt: &str,
) -> Result<()> {
    tracing::info!("Pushing initial prompt to event store...");
    let content = rig::message::UserContent::Text(rig::message::Text { text: prompt.to_owned() });
    let event = dabgent_agent::event::Event::UserMessage(rig::OneOrMany::one(content));
    store
        .push_event(stream_id, aggregate_id, &event, &Default::default())
        .await
        .map_err(Into::into)
}
