use dabgent_agent::processor::{CompletionProcessor, DelegationProcessor, FinishProcessor, Pipeline, Processor, ThreadProcessor, ToolProcessor};
use dabgent_agent::toolbox::ToolDyn;
use dabgent_fastapi::{toolset::dataapps_toolset, validator::DataAppsValidator, artifact_preparer::DataAppsArtifactPreparer};
use dabgent_fastapi::templates::{EMBEDDED_TEMPLATES, DEFAULT_TEMPLATE_PATH};
use dabgent_mq::{EventStore, create_store, StoreConfig};
use dabgent_sandbox::{Sandbox, dagger::{ConnectOpts, Sandbox as DaggerSandbox}};
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
        let claude_llm = rig::providers::anthropic::Client::from_env();
        let store = create_store(Some(StoreConfig::from_env())).await?;
        tracing::info!("Event store initialized successfully");
        let sandbox = create_sandbox(&client).await?;
        let tool_processor_tools = dataapps_toolset(DataAppsValidator::new());
        let finish_processor_tools = dataapps_toolset(DataAppsValidator::new());

        push_llm_config(&store, STREAM_ID, AGGREGATE_ID, &tool_processor_tools).await?;

        // Use embedded templates in release mode, filesystem in debug mode
        let template_path = if cfg!(debug_assertions) {
            DEFAULT_TEMPLATE_PATH
        } else {
            EMBEDDED_TEMPLATES
        };

        push_seed_sandbox(&store, STREAM_ID, AGGREGATE_ID, template_path, "/app").await?;
        push_prompt(&store, STREAM_ID, AGGREGATE_ID, USER_PROMPT).await?;

        tracing::info!("Starting DataApps pipeline with main model: {} and delegation model: {}", MAIN_MODEL, DELEGATION_MODEL);

        let thread_processor = ThreadProcessor::new(claude_llm.clone(), store.clone());

        // Create export directory path with timestamp
        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let export_path = format!("/tmp/dataapps_output_{}", timestamp);

        // Fork sandbox for completion processor
        let completion_sandbox = sandbox.fork().await?;
        let tool_processor = ToolProcessor::new(dabgent_sandbox::Sandbox::boxed(sandbox), store.clone(), tool_processor_tools, None);

        let delegation_processor = DelegationProcessor::new(
            store.clone(),
            DELEGATION_MODEL.to_string(),
            vec![
                Box::new(dabgent_agent::processor::delegation::databricks::DatabricksHandler::new()?),
                Box::new(dabgent_agent::processor::delegation::compaction::CompactionHandler::new(2048)?),
            ],
        );

        // FixMe: FinishProcessor should have no state, including export path
        let finish_processor = FinishProcessor::new_with_preparer(
            dabgent_sandbox::Sandbox::boxed(completion_sandbox),
            store.clone(),
            export_path.clone(),
            finish_processor_tools,
            DataAppsArtifactPreparer,
        );

        let completion_processor = CompletionProcessor::new(store.clone());
        let pipeline = Pipeline::new(
            store.clone(),
            vec![
                thread_processor.boxed(),
                tool_processor.boxed(),           // Handles main thread tools (recipient: None)
                completion_processor.boxed(),     // Handles Done and FinishDelegation completions
                delegation_processor.boxed(),     // Handles delegation AND delegated tool execution (including compaction)
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

Data Sources:
- You have access to Databricks Unity Catalog with bakery business data
- Use the 'explore_databricks_catalog' tool to discover available tables and schemas
- The catalog contains real business data about products, sales, customers, and orders
- Once you explore the data, use the actual schema and sample data for your API design

Your Task:
1. First, explore the Databricks catalog to understand the data
2. Create a data API that serves real data from Databricks tables
3. Configure React Admin UI to display this data in tables
4. Ensure CORS is properly configured for React Admin
5. When the app is ready, you need to use tool Done to run the tests and linters. If there are any errors, fix them; otherwise, the tool will confirm completion.

Implementation Details:
- Start by exploring the Databricks catalog to find relevant tables
- Design API endpoints based on the actual data structure you discover
- Each endpoint should return data with fields matching the Databricks schema
- Update frontend/src/App.tsx to add Resources for the discovered data
- Include X-Total-Count header for React Admin pagination

";

const USER_PROMPT: &str = "
Create a data app to show the core sales data for a bakery.

1. First, explore the Databricks catalog to discover where bakery sales data is stored, i assume it is under `samples` but you need to confirm;
2. Based on what you find, create backend API endpoints with some sample data from those tables (real integration will be added later);
3. Build React Admin frontend that displays the discovered data in tables

Focus on creating a functional DataApp that showcases real bakery business data from Databricks.
";


const MAIN_MODEL: &str = "claude-sonnet-4-5";
const DELEGATION_MODEL: &str = "claude-sonnet-4-5";

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
        model: MAIN_MODEL.to_owned(),
        temperature: 0.0,
        max_tokens: 8192,
        preamble: Some(SYSTEM_PROMPT.to_owned()),
        tools: Some(tool_definitions),
        recipient: None,
        parent: None,
    };
    store
        .push_event(stream_id, aggregate_id, &event, &Default::default())
        .await
        .map_err(Into::into)
}

async fn push_seed_sandbox<S: EventStore>(
    store: &S,
    stream_id: &str,
    aggregate_id: &str,
    template_path: &str,
    base_path: &str,
) -> Result<()> {
    tracing::info!("Pushing seed sandbox event: {}", template_path);
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
