use crate::llm::{Completion, CompletionResponse, LLMClient, WithRetryExt};
use crate::{Aggregate, Event, Processor};
use dabgent_mq::{EventDb, EventStore, Query};
use eyre::Result;
use rig::completion::ToolDefinition;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Command {
    Setup {
        model: String,
        temperature: f64,
        max_tokens: u64,
        preamble: Option<String>,
        tools: Option<Vec<ToolDefinition>>,
        recipient: Option<String>,
    },
    Agent(CompletionResponse),
    User(rig::OneOrMany<rig::message::UserContent>),
}

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("Model is not configured")]
    Uninitialized,
    #[error("Wrong turn")]
    WrongTurn,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Thread {
    pub recipient: Option<String>,
    pub model: Option<String>,
    pub temperature: Option<f64>,
    pub max_tokens: Option<u64>,
    pub preamble: Option<String>,
    pub tools: Option<Vec<ToolDefinition>>,
    pub messages: Vec<rig::completion::Message>,
}

impl Aggregate for Thread {
    type Command = Command;
    type Event = Event;
    type Error = Error;

    fn process(&mut self, command: Self::Command) -> Result<Vec<Self::Event>, Self::Error> {
        let events = match command {
            Command::Setup { .. } => self.handle_setup(command)?,
            Command::Agent(..) => self.handle_agent(command)?,
            Command::User(..) => self.handle_user(command)?,
        };
        for event in events.iter() {
            self.apply(&event);
        }
        Ok(events)
    }

    fn apply(&mut self, event: &Self::Event) {
        match event {
            Event::LLMConfig {
                model,
                temperature,
                max_tokens,
                preamble,
                tools,
                recipient,
                parent: _,
            } => {
                self.model = Some(model.clone());
                self.temperature = Some(temperature.clone());
                self.max_tokens = Some(max_tokens.clone());
                self.preamble = preamble.clone();
                self.tools = tools.clone();
                self.recipient = recipient.clone();
            }
            Event::AgentMessage { response, .. } => {
                self.messages.push(response.message());
            }
            Event::UserMessage(content) => {
                self.messages.push(rig::completion::Message::User {
                    content: content.clone(),
                });
            }
            _ => {}
        }
    }
}

impl Thread {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn handle_setup(&self, command: Command) -> Result<Vec<Event>, Error> {
        match command {
            Command::Setup {
                model,
                temperature,
                max_tokens,
                preamble,
                tools,
                recipient,
            } => Ok(vec![Event::LLMConfig {
                model,
                temperature: temperature,
                max_tokens: max_tokens,
                preamble,
                tools,
                recipient,
                parent: None,
            }]),
            _ => unreachable!(),
        }
    }

    pub fn handle_user(&self, command: Command) -> Result<Vec<Event>, Error> {
        if self.model.is_none() || self.temperature.is_none() || self.max_tokens.is_none() {
            return Err(Error::Uninitialized);
        }
        match command {
            Command::User(content) => match self.messages.last() {
                None | Some(rig::completion::Message::Assistant { .. }) => {
                    Ok(vec![Event::UserMessage(content)])
                }
                _ => Err(Error::WrongTurn),
            },
            _ => unreachable!(),
        }
    }

    pub fn handle_agent(&self, command: Command) -> Result<Vec<Event>, Error> {
        match command {
            Command::Agent(response) => match self.messages.last() {
                Some(rig::completion::Message::User { .. }) => Ok(vec![Event::AgentMessage {
                    response,
                    recipient: self.recipient.clone(),
                }]),
                _ => Err(Error::WrongTurn),
            },
            _ => unreachable!(),
        }
    }
}

pub struct ThreadProcessor<T: LLMClient, E: EventStore> {
    llm: T,
    event_store: E,
}

impl<T: LLMClient, E: EventStore> Processor<Event> for ThreadProcessor<T, E> {
    async fn run(&mut self, event: &EventDb<Event>) -> eyre::Result<()> {
        let query = Query::stream(&event.stream_id).aggregate(&event.aggregate_id);
        match &event.data {
            Event::UserMessage(..) | Event::ToolResult(..) => {
                let events = self.event_store.load_events::<Event>(&query, None).await?;
                let mut thread = Thread::fold(&events);
                let completion = self.completion(&thread).await?;
                let new_events = thread.process(Command::Agent(completion))?;
                for new_event in new_events.iter() {
                    self.event_store
                        .push_event(
                            &event.stream_id,
                            &event.aggregate_id,
                            new_event,
                            &Default::default(),
                        )
                        .await?;
                }
            }
            _ => {}
        }
        Ok(())
    }
}

impl<T: LLMClient, E: EventStore> ThreadProcessor<T, E> {
    pub fn new(llm: T, event_store: E) -> Self {
        Self { llm, event_store }
    }

    pub async fn completion(&self, thread: &Thread) -> Result<CompletionResponse> {
        let mut history = thread.messages.clone();
        let message = history.pop().expect("No messages");
        let mut completion = Completion::new(thread.model.clone().unwrap(), message)
            .history(history)
            .temperature(thread.temperature.unwrap())
            .max_tokens(thread.max_tokens.unwrap());
        if let Some(preamble) = &thread.preamble {
            completion = completion.preamble(preamble.clone());
        }
        if let Some(ref tools) = thread.tools {
            completion = completion.tools(tools.clone());
        }
        let llm = self.llm.clone().with_retry();
        llm.completion(completion).await
    }
}
