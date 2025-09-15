use crate::session::{ChatCommand, ChatEvent, ChatSession};
use dabgent_agent::handler::Handler;
use dabgent_agent::planning::PlanningAgent;
use dabgent_mq::db::{EventStore, Metadata, Query};
use dabgent_sandbox::Sandbox;
use dabgent_sandbox::dagger::Sandbox as DaggerSandbox;
use std::env;

pub struct Agent<S: EventStore> {
    store: S,
    stream_id: String,
    aggregate_id: String,
}

impl<S: EventStore> Agent<S> {
    pub fn new(store: S, stream_id: String, aggregate_id: String) -> Self {
        Self {
            store,
            stream_id,
            aggregate_id,
        }
    }

    pub async fn run(self) -> color_eyre::Result<()> {
        dagger_sdk::connect(|client| async move {
            let sandbox = create_sandbox(&client).await?;
            let llm = create_llm()?;

            let planning_agent = PlanningAgent::new(
                self.store.clone(),
                self.stream_id.clone(),
                self.aggregate_id.clone(),
            );

            planning_agent.setup_workers(sandbox.boxed(), llm).await?;

            let mut event_stream = self.store.subscribe::<ChatEvent>(&Query {
                stream_id: self.stream_id.clone(),
                event_type: Some("user_message".to_string()),
                aggregate_id: Some(self.aggregate_id.clone()),
            })?;

            while let Some(Ok(ChatEvent::UserMessage { content, .. })) = event_stream.next().await {
                let agent = PlanningAgent::new(
                    self.store.clone(),
                    self.stream_id.clone(),
                    self.aggregate_id.clone(),
                );

                agent.process_message(content).await?;

                let store = self.store.clone();
                let stream_id = self.stream_id.clone();
                let aggregate_id = self.aggregate_id.clone();

                agent
                    .monitor_progress(move |status| {
                        let store = store.clone();
                        let stream_id = stream_id.clone();
                        let aggregate_id = aggregate_id.clone();
                        Box::pin(async move {
                            send_agent_message(&store, &stream_id, &aggregate_id, status)
                                .await
                                .map_err(|e| eyre::eyre!(e))
                        })
                    })
                    .await?;
            }
            Ok(())
        })
        .await?;
        Ok(())
    }
}

async fn send_agent_message<S: EventStore>(
    store: &S,
    stream_id: &str,
    aggregate_id: &str,
    content: String,
) -> color_eyre::Result<()> {
    let events = store
        .load_events::<ChatEvent>(
            &Query {
                stream_id: stream_id.to_string(),
                event_type: None,
                aggregate_id: Some(aggregate_id.to_string()),
            },
            None,
        )
        .await?;

    let mut session = ChatSession::fold(&events);
    let new_events = session.process(ChatCommand::AgentRespond(content))?;

    for event in new_events {
        store
            .push_event(stream_id, aggregate_id, &event, &Metadata::default())
            .await?;
    }
    Ok(())
}

fn create_llm() -> color_eyre::Result<rig::providers::anthropic::Client> {
    Ok(rig::providers::anthropic::Client::new(
        &env::var("ANTHROPIC_API_KEY")
            .or_else(|_| env::var("OPENAI_API_KEY"))
            .map_err(|_| eyre::eyre!("Please set ANTHROPIC_API_KEY or OPENAI_API_KEY"))?,
    ))
}

async fn create_sandbox(client: &dagger_sdk::DaggerConn) -> color_eyre::Result<DaggerSandbox> {
    let dockerfile = env::var("SANDBOX_DOCKERFILE").unwrap_or_else(|_| "Dockerfile".to_owned());
    let context_dir = env::var("SANDBOX_CONTEXT_DIR").unwrap_or_else(|_| {
        let mut path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        path.push("../dabgent_agent/examples");
        path.canonicalize()
            .unwrap_or_else(|_| std::path::PathBuf::from("./dabgent_agent/examples"))
            .to_string_lossy()
            .to_string()
    });

    let ctr = client.container().build_opts(
        client.host().directory(&context_dir),
        dagger_sdk::ContainerBuildOptsBuilder::default()
            .dockerfile(dockerfile.as_str())
            .build()?,
    );
    ctr.sync().await?;
    Ok(DaggerSandbox::from_container(ctr))
}
