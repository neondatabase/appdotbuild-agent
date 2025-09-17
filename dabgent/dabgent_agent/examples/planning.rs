use dabgent_agent::llm::{LLMClient, Completion};
use dabgent_agent::pipeline::PipelineBuilder;
use dabgent_agent::toolbox::{self, basic::{toolset_with_tasklist, TaskList}};
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
        let planning_tools = toolset_with_tasklist(NoOpValidator, LlmTaskList::new(llm.clone()));

        push_prompt(&store, STREAM_ID, AGGREGATE_ID, USER_PROMPT).await?;

        let pipeline = PipelineBuilder::new()
            .llm(llm)
            .store(store)
            .sandbox(sandbox.boxed())
            .model(MODEL.to_owned())
            .preamble(SYSTEM_PROMPT.to_owned())
            .tools(planning_tools)
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
You are also a planning expert who breaks down complex tasks to planning.md file and updates them there after each step.
";

const USER_PROMPT: &str = "An application to retrieve weather data for a given location";

const MODEL: &str = "claude-sonnet-4-20250514";
const LLM_UNIVERSAL_MODEL: &str = "claude-sonnet-4-20250514";

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

pub struct NoOpValidator;

impl toolbox::Validator for NoOpValidator {
    async fn run(&self, _sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<(), String>> {
        Ok(Ok(()))
    }
}

pub struct LlmTaskList {
    llm: rig::providers::anthropic::Client,
}

impl LlmTaskList {
    fn new(llm: rig::providers::anthropic::Client) -> Self {
        Self { llm }
    }
}

impl TaskList for LlmTaskList {
    fn update(&self, current_content: String) -> Result<String> {
        let update_prompt = format!(
            "You are a task management assistant. Here is the current planning.md file content:\n\n{}\n\n\
            Please update this markdown file to reflect the current state of tasks. \
            You can add new tasks, mark completed ones, update progress, or reorganize as needed. \
            Return only the updated markdown content without any additional explanation.",
            current_content
        );

        let completion = Completion::new(
            LLM_UNIVERSAL_MODEL.to_string(),
            rig::message::Message::user(update_prompt),
        )
        .max_tokens(2048);

        // Use tokio's block_on to run async code synchronously
        let response = tokio::task::block_in_place(|| {
            tokio::runtime::Handle::current().block_on(async {
                self.llm.completion(completion).await
            })
        })
        .map_err(|e| eyre::eyre!("Failed to call LLM: {}", e))?;

        // Extract text content from the response
        let content = response.choice.iter()
            .find_map(|item| {
                if let rig::message::AssistantContent::Text(text) = item {
                    Some(text.to_string())
                } else {
                    None
                }
            })
            .ok_or_else(|| eyre::eyre!("No text content in response"))?;

        Ok(content)
    }
}
