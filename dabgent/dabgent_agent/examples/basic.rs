use dabgent_agent::llm::LLMClient;
use dabgent_agent::processor::{Pipeline, Processor, ThreadProcessor, ToolProcessor};
use dabgent_agent::toolbox::{self, basic::toolset};
use dabgent_mq::{EventStore, db::sqlite::SqliteStore};
use dabgent_sandbox::dagger::{ConnectOpts, Sandbox as DaggerSandbox};
use dabgent_sandbox::{Sandbox, SandboxDyn};
use eyre::Result;
use rig::client::ProviderClient;

const ANTHROPIC_MODEL: &str = "claude-sonnet-4.5-20250929";
const OPENROUTER_MODEL: &str = "deepseek/deepseek-v3.2-exp";

const SYSTEM_PROMPT: &str = "
You are a python software engineer.
Workspace is already set up using uv init.
Use uv package manager if you need to add extra libraries.
Program will be run using uv run main.py command.
";

#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt::init();

    const STREAM_ID: &str = "pipeline";
    let prompt = "minimal script that fetches my ip using some api like ipify.org";

    // Determine which provider to use based on available API keys
    let (use_anthropic, model) = if std::env::var("ANTHROPIC_API_KEY").is_ok() {
        (true, ANTHROPIC_MODEL)
    } else if std::env::var("OPENROUTER_API_KEY").is_ok() {
        (false, OPENROUTER_MODEL)
    } else {
        panic!("Either ANTHROPIC_API_KEY or OPENROUTER_API_KEY must be set");
    };

    let store = store().await;

    // Get tool definitions
    let tools = dabgent_agent::toolbox::basic::toolset(Validator);
    let tool_definitions: Vec<rig::completion::ToolDefinition> = tools
        .iter()
        .map(|tool| tool.definition())
        .collect();

    push_llm_config(&store, STREAM_ID, "", model, tool_definitions).await.unwrap();
    push_prompt(&store, STREAM_ID, "", prompt).await.unwrap();

    // Run pipeline with appropriate LLM client
    if use_anthropic {
        let llm = rig::providers::anthropic::Client::from_env();
        pipeline_fn(STREAM_ID, store, llm).await.unwrap();
    } else {
        let llm = rig::providers::openrouter::Client::from_env();
        pipeline_fn(STREAM_ID, store, llm).await.unwrap();
    }
}

pub async fn pipeline_fn<T: LLMClient + Clone + 'static>(
    stream_id: &str,
    store: impl EventStore,
    llm: T,
) -> Result<()> {
    let stream_id = stream_id.to_owned();
    let opts = ConnectOpts::default();
    opts.connect(move |client| async move {
        let sandbox = sandbox(&client).await?;
        let tools = toolset(Validator);

        let thread_processor = ThreadProcessor::new(llm.clone(), store.clone());
        let tool_processor = ToolProcessor::new(sandbox.boxed(), store.clone(), tools, None);
        let pipeline = Pipeline::new(
            store.clone(),
            vec![thread_processor.boxed(), tool_processor.boxed()],
        );
        pipeline.run(stream_id.clone()).await?;
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

async fn push_llm_config<S: EventStore>(
    store: &S,
    stream_id: &str,
    aggregate_id: &str,
    model: &str,
    tool_definitions: Vec<rig::completion::ToolDefinition>,
) -> Result<()> {
    let event = dabgent_agent::event::Event::LLMConfig {
        model: model.to_owned(),
        temperature: 0.1,
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

async fn push_prompt<S: EventStore>(
    store: &S,
    stream_id: &str,
    aggregate_id: &str,
    prompt: &str,
) -> Result<()> {
    let user_content = rig::message::UserContent::Text(rig::message::Text { text: prompt.to_owned() });
    let event = dabgent_agent::event::Event::UserMessage(rig::OneOrMany::one(user_content));
    store
        .push_event(stream_id, aggregate_id, &event, &Default::default())
        .await
        .map_err(Into::into)
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
