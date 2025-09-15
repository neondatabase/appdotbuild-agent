use crate::handler::Handler;
use crate::llm::{Completion, CompletionResponse, LLMClient};
use crate::thread::{Command, Event, Thread, ToolResponse};
use crate::toolbox::{ToolCallExt, ToolDyn};
use dabgent_mq::EventStore;
use dabgent_sandbox::SandboxDyn;
use eyre::Result;
use rig::completion::ToolDefinition;

pub struct Worker<T: LLMClient, E: EventStore> {
    llm: T,
    event_store: E,
    model: String,
    preamble: String,
    temperature: f64,
    max_tokens: u64,
    tools: Vec<ToolDefinition>,
}

impl<T: LLMClient, E: EventStore> Worker<T, E> {
    pub fn new(
        llm: T,
        event_store: E,
        model: String,
        preamble: String,
        tools: Vec<ToolDefinition>,
    ) -> Self {
        Worker {
            llm,
            event_store,
            model,
            preamble,
            temperature: 1.0,
            max_tokens: 8192,
            tools,
        }
    }

    pub async fn run(&self, stream_id: &str, aggregate_id: &str) -> Result<()> {
        let query = dabgent_mq::db::Query {
            stream_id: stream_id.to_owned(),
            event_type: None,
            aggregate_id: Some(aggregate_id.to_owned()),
        };
        let mut receiver = self.event_store.subscribe::<Event>(&query)?;
        while let Some(event) = receiver.next().await {
            if let Err(error) = event {
                tracing::error!(?error, "llm worker");
                continue;
            }
            match event.unwrap() {
                Event::Prompted(..) | Event::ToolCompleted(..) => {
                    let events = self.event_store.load_events::<Event>(&query, None).await?;
                    let mut thread = Thread::fold(&events);
                    let completion = self.completion(&thread).await?;
                    let new_events = thread.process(Command::Completion(completion))?;
                    for event in new_events.iter() {
                        self.event_store
                            .push_event(stream_id, aggregate_id, event, &Default::default())
                            .await?;
                    }
                }
                _ => continue,
            }
        }
        Ok(())
    }

    pub async fn completion(&self, thread: &Thread) -> Result<CompletionResponse> {
        let mut history = thread.messages.clone();
        let message = history.pop().expect("No messages");
        let completion = Completion::new(self.model.clone(), message)
            .history(history)
            .preamble(self.preamble.clone())
            .tools(self.tools.clone())
            .temperature(self.temperature)
            .max_tokens(self.max_tokens);
        self.llm.completion(completion).await
    }

    pub fn temperature(mut self, temperature: f64) -> Self {
        self.temperature = temperature;
        self
    }

    pub fn max_tokens(mut self, max_tokens: u64) -> Self {
        self.max_tokens = max_tokens;
        self
    }
}

pub struct ToolWorker<E: EventStore> {
    sandbox: Box<dyn SandboxDyn>,
    event_store: E,
    tools: Vec<Box<dyn ToolDyn>>,
}

impl<E: EventStore> ToolWorker<E> {
    pub fn new(sandbox: Box<dyn SandboxDyn>, event_store: E, tools: Vec<Box<dyn ToolDyn>>) -> Self {
        Self {
            sandbox,
            event_store,
            tools,
        }
    }

    pub async fn run(&mut self, stream_id: &str, aggregate_id: &str) -> Result<()> {
        let query = dabgent_mq::db::Query {
            stream_id: stream_id.to_owned(),
            event_type: Some("llm_completed".to_owned()),
            aggregate_id: Some(aggregate_id.to_owned()),
        };
        let mut receiver = self.event_store.subscribe::<Event>(&query)?;
        while let Some(event) = receiver.next().await {
            match event {
                Ok(Event::LlmCompleted(response)) if Thread::has_tool_calls(&response) => {
                    let events = self.event_store.load_events::<Event>(&query, None).await?;
                    let mut thread = Thread::fold(&events);
                    let tools = self.run_tools(&response).await?;
                    let command = {
                        let tools = tools.into_iter().map(rig::message::UserContent::ToolResult);
                        ToolResponse {
                            content: rig::OneOrMany::many(tools)?,
                        }
                    };
                    let new_events = thread.process(Command::Tool(command))?;
                    for event in new_events.iter() {
                        self.event_store
                            .push_event(stream_id, aggregate_id, event, &Default::default())
                            .await?;
                    }
                }
                Err(error) => {
                    tracing::error!(?error, "sandbox worker");
                }
                _ => continue,
            }
        }
        Ok(())
    }

    async fn run_tools(
        &mut self,
        response: &CompletionResponse,
    ) -> Result<Vec<rig::message::ToolResult>> {
        let mut results = Vec::new();
        for content in response.choice.iter() {
            if let rig::message::AssistantContent::ToolCall(call) = content {
                let tool = self.tools.iter().find(|t| t.name() == call.function.name);
                let result = match tool {
                    Some(tool) => {
                        let args = call.function.arguments.clone();
                        tool.call(args, &mut self.sandbox).await?
                    }
                    None => {
                        let error = format!("{} not found", call.function.name);
                        Err(serde_json::json!(error))
                    }
                };
                results.push(call.to_result(result));
            }
        }
        Ok(results)
    }
}
