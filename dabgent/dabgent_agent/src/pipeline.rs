use crate::agent::{ToolWorker, Worker};
use crate::handler::Handler;
use crate::llm::LLMClient;
use crate::thread::{self, Event, Thread};
use crate::toolbox::ToolDyn;
use dabgent_mq::{EventStore, db::Query};
use dabgent_sandbox::SandboxDyn;
use eyre::{OptionExt, Result};

pub struct PipelineBuilder<T, S>
where
    T: LLMClient,
    S: EventStore,
{
    llm: Option<T>,
    store: Option<S>,
    model: Option<String>,
    preamble: Option<String>,
    sandbox: Option<Box<dyn SandboxDyn>>,
    tools: Vec<Box<dyn ToolDyn>>,
    _worker_marker: std::marker::PhantomData<Worker<T, S>>,
    _sandbox_marker: std::marker::PhantomData<Box<dyn SandboxDyn>>,
}

impl<T, S> PipelineBuilder<T, S>
where
    T: LLMClient,
    S: EventStore,
{
    pub fn new() -> Self {
        Self {
            llm: None,
            store: None,
            sandbox: None,
            model: None,
            preamble: None,
            tools: Vec::new(),
            _worker_marker: std::marker::PhantomData,
            _sandbox_marker: std::marker::PhantomData,
        }
    }

    pub fn llm(mut self, llm: T) -> Self {
        self.llm = Some(llm);
        self
    }

    pub fn store(mut self, store: S) -> Self {
        self.store = Some(store);
        self
    }

    pub fn sandbox(mut self, sandbox: Box<dyn SandboxDyn>) -> Self {
        self.sandbox = Some(sandbox);
        self
    }

    pub fn model(mut self, model: String) -> Self {
        self.model = Some(model);
        self
    }

    pub fn preamble(mut self, preamble: String) -> Self {
        self.preamble = Some(preamble);
        self
    }

    pub fn tool(mut self, tool: Box<dyn ToolDyn>) -> Self {
        self.tools.push(tool);
        self
    }

    pub fn tools(mut self, tools: Vec<Box<dyn ToolDyn>>) -> Self {
        self.tools.extend(tools);
        self
    }

    pub fn build(self) -> Result<Pipeline<T, S>> {
        let llm = self.llm.ok_or_eyre("LLM Client not provided")?;
        let store = self.store.ok_or_eyre("Event Store not provided")?;
        let model = self.model.ok_or_eyre("Model not provided")?;
        let preamble = self.preamble.ok_or_eyre("Preamble not provided")?;
        let sandbox = self.sandbox.ok_or_eyre("Sandbox not provided")?;

        let tool_defs = self.tools.iter().map(|tool| tool.definition()).collect();
        let llm_worker = Worker::new(llm, store.clone(), model, preamble, tool_defs);
        let tool_worker = ToolWorker::new(sandbox, store.clone(), self.tools);

        Ok(Pipeline::new(store, llm_worker, tool_worker))
    }
}

pub struct Pipeline<T, S>
where
    T: LLMClient,
    S: EventStore,
{
    store: S,
    llm_worker: Worker<T, S>,
    tool_worker: ToolWorker<S>,
}

impl<T, S> Pipeline<T, S>
where
    T: LLMClient,
    S: EventStore,
{
    pub fn new(store: S, llm_worker: Worker<T, S>, tool_worker: ToolWorker<S>) -> Self {
        Self {
            store,
            llm_worker,
            tool_worker,
        }
    }

    pub async fn run(self, stream_id: String, aggregate_id: String) -> Result<()> {
        let Self {
            store,
            llm_worker,
            mut tool_worker,
        } = self;
        tokio::select! {
            res = llm_worker.run(&stream_id, &aggregate_id) => {
                tracing::error!("LLM worker failed: {:?}", res);
                res
            },
            res = tool_worker.run(&stream_id, &aggregate_id) => {
                tracing::error!("Tool worker failed: {:?}", res);
                res
            },
            res = Self::subscriber(&store, &stream_id, &aggregate_id) => res,
        }
    }

    pub async fn subscriber(store: &S, stream_id: &str, aggregate_id: &str) -> Result<()> {
        let query = Query {
            stream_id: stream_id.to_owned(),
            event_type: None,
            aggregate_id: Some(aggregate_id.to_owned()),
        };
        let mut receiver = store.subscribe::<Event>(&query)?;
        let mut events = store.load_events(&query, None).await?;
        while let Some(event) = receiver.next().await {
            let event = event?;
            events.push(event.clone());
            let thread = Thread::fold(&events);
            tracing::info!(?thread.state, ?event, "event");
            match thread.state {
                thread::State::Done => break,
                _ => continue,
            }
        }
        Ok(())
    }
}
