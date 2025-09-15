use dabgent_agent::pipeline::PipelineBuilder;
use dabgent_agent::toolbox::{self, basic::toolset};
use dabgent_mq::{EventStore, db::sqlite::SqliteStore};
use dabgent_sandbox::dagger::{ConnectOpts, Sandbox as DaggerSandbox};
use dabgent_sandbox::{Sandbox, SandboxDyn};
use eyre::Result;
use rig::client::ProviderClient;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    const STREAM_ID: &str = "pipeline";
    const AGGREGATE_ID: &str = "thread";

    let opts = ConnectOpts::default();
    opts.connect(|client| async move {
        let llm = rig::providers::anthropic::Client::from_env();
        let sandbox = sandbox(&client).await?;
        let store = store().await;
        let tools = toolset(Validator);

        push_prompt(&store, STREAM_ID, AGGREGATE_ID, USER_PROMPT).await?;

        let pipeline = PipelineBuilder::new()
            .llm(llm)
            .store(store)
            .sandbox(sandbox.boxed())
            .model(MODEL.to_owned())
            .preamble(SYSTEM_PROMPT.to_owned())
            .tools(tools)
            .build()?;

        pipeline
            .run(STREAM_ID.to_owned(), AGGREGATE_ID.to_owned())
            .await
    })
    .await
    .unwrap();
}

const SYSTEM_PROMPT: &str = "
You are a python software engineer.
Workspace is already set up using uv init.
Use uv package manager if you need to add extra libraries.
Program will be run using uv run main.py command.
";

const USER_PROMPT: &str = "minimal script that fetches my ip using some api like ipify.org";

const MODEL: &str = "claude-sonnet-4-20250514";

async fn sandbox(client: &dagger_sdk::DaggerConn) -> Result<DaggerSandbox> {
    let opts = dagger_sdk::ContainerBuildOptsBuilder::default()
        .dockerfile("Dockerfile")
        .build()?;
    let ctr = client
        .container()
        .build_opts(client.host().directory("./examples"), opts);
    ctr.sync().await?;
    let sandbox = DaggerSandbox::from_container(ctr);
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

async fn push_prompt<S: EventStore>(
    store: &S,
    stream_id: &str,
    aggregate_id: &str,
    prompt: &str,
) -> Result<()> {
    let event = dabgent_agent::thread::Event::Prompted(prompt.to_owned());
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
