use crate::llm::CompletionResponse;
use dabgent_mq::listener::EventQueue;
use dabgent_mq::{Aggregate, Callback, Envelope, Event as MQEvent, EventStore, Handler, Listener};
use eyre::Result;
use rig::message::{ToolCall, ToolResult};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Command<T> {
    PutUserMessage {
        content: rig::OneOrMany<rig::message::UserContent>,
    },
    PutToolCalls {
        calls: Vec<ToolCall>,
    },
    PutCompletion {
        response: CompletionResponse,
    },
    PutToolResults {
        results: Vec<ToolResult>,
    },
    Agent(T),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Event<T> {
    UserCompletion {
        content: rig::OneOrMany<rig::message::UserContent>,
    },
    ToolCalls {
        calls: Vec<ToolCall>,
    },
    AgentCompletion {
        response: CompletionResponse,
    },
    ToolResults {
        results: Vec<ToolResult>,
    },
    Agent(T),
}

impl<T: MQEvent> MQEvent for Event<T> {
    fn event_version(&self) -> String {
        match self {
            Event::Agent(inner) => inner.event_version(),
            _ => "1.0".to_owned(),
        }
        .to_owned()
    }

    fn event_type(&self) -> String {
        match self {
            Event::UserCompletion { .. } => "user.completion".to_owned(),
            Event::ToolCalls { .. } => "tool.calls".to_owned(),
            Event::AgentCompletion { .. } => "agent.completion".to_owned(),
            Event::ToolResults { .. } => "tool.results".to_owned(),
            inner => inner.event_type(),
        }
    }
}

pub trait Agent: Default + Send + Sync + Clone {
    const TYPE: &'static str;
    type AgentCommand: Send;
    type AgentEvent: MQEvent;
    type AgentError: std::error::Error + Send + Sync + 'static;
    type Services: Send + Sync;

    fn handle_tool_results(
        state: &AgentState<Self>,
        services: &Self::Services,
        incoming: Vec<ToolResult>,
    ) -> impl Future<Output = Result<Vec<Event<Self::AgentEvent>>, Self::AgentError>> + Send;

    #[allow(unused)]
    fn handle_command(
        state: &AgentState<Self>,
        cmd: Self::AgentCommand,
        services: &Self::Services,
    ) -> impl Future<Output = Result<Vec<Event<Self::AgentEvent>>, Self::AgentError>> + Send {
        async { Ok(vec![]) }
    }

    fn apply_event(state: &mut AgentState<Self>, event: Event<Self::AgentEvent>);
}

#[derive(Clone, Default, Debug)]
pub struct AgentState<A: Agent> {
    pub agent: A,
    pub calls: HashMap<String, Option<ToolResult>>,
    pub messages: Vec<rig::message::Message>,
}

impl<A: Agent> AgentState<A> {
    pub fn all_tools_ready(&self) -> bool {
        self.calls.values().all(|result| result.is_some())
    }

    pub fn check_ready(&self, incoming: &[ToolResult]) -> bool {
        for (id, result) in self.calls.iter() {
            if result.is_none() && incoming.iter().find(|r| r.id == *id).is_none() {
                return false;
            }
        }
        true
    }

    pub fn merge_tool_results(&self, mut incoming: Vec<ToolResult>) -> Vec<ToolResult> {
        incoming.extend(self.calls.values().filter_map(|r| r.clone()));
        incoming
    }
}

impl<A: Agent> Aggregate for AgentState<A> {
    const TYPE: &'static str = A::TYPE;
    type Command = Command<A::AgentCommand>;
    type Event = Event<A::AgentEvent>;
    type Services = A::Services;
    type Error = AgentError<A::AgentError>;

    async fn handle(
        &self,
        cmd: Self::Command,
        services: &Self::Services,
    ) -> Result<Vec<Self::Event>, Self::Error> {
        match cmd {
            Command::SendRequest(request) => match request {
                Request::Completion { content } => {
                    if !self.all_tools_ready() {
                        return Err(Error::NotReady.into());
                    }
                    Ok(vec![Event::Request(Request::Completion { content })])
                }
                Request::ToolCalls { calls } => {
                    Ok(vec![Event::Request(Request::ToolCalls { calls })])
                }
            },
            Command::SendResponse(response) => {
                let mut events = vec![Event::Response(response.clone())];
                match response {
                    Response::ToolResults { results } => {
                        if let Some(call) = results.iter().find(|c| !self.calls.contains_key(&c.id))
                        {
                            return Err(Error::UnexpectedTool(call.id.clone()).into());
                        }
                        if self.check_ready(&results) {
                            let agent_events = A::handle_tool_results(self, services, results)
                                .await
                                .map_err(AgentError::Agent)?;
                            events.extend(agent_events);
                        }
                    }
                    Response::Completion { response } => {
                        if let Some(calls) = response.tool_calls() {
                            events.push(Event::Request(Request::ToolCalls { calls }))
                        }
                    }
                }
                Ok(events)
            }
            Command::Agent(cmd) => {
                let events = A::handle_command(self, cmd, services)
                    .await
                    .map_err(AgentError::Agent)?;
                Ok(events)
            }
        }
    }

    fn apply(&mut self, event: Self::Event) {
        match event.clone() {
            Event::Request(request) => match &request {
                Request::Completion { content } => {
                    self.messages.push(rig::message::Message::User {
                        content: content.clone(),
                    });
                    self.calls.clear();
                }
                Request::ToolCalls { calls } => {
                    for call in calls {
                        self.calls.insert(call.id.clone(), None);
                    }
                }
            },
            Event::Response(response) => match response {
                Response::Completion { response } => {
                    self.messages.push(response.message());
                }
                Response::ToolResults { results } => {
                    for result in results {
                        self.calls.insert(result.id.clone(), Some(result));
                    }
                }
            },
            _ => {}
        }
        A::apply_event(self, event);
    }
}

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("Invalid state transition")]
    InvalidState,
    #[error("Not ready for completion")]
    NotReady,
    #[error("Unexpected tool result with id: {0}")]
    UnexpectedTool(String),
}

#[derive(Debug, thiserror::Error)]
pub enum AgentError<E: std::error::Error> {
    #[error("Shared error: {0}")]
    Shared(#[from] Error),
    #[error("Agent error: {0}")]
    Agent(#[source] E),
}

pub trait EventHandler<A: Agent, ES: EventStore>: Send {
    fn process(
        &mut self,
        handler: &Handler<AgentState<A>, ES>,
        event: &Envelope<AgentState<A>>,
    ) -> impl Future<Output = Result<()>> + Send;
}

pub struct HandlerAdapter<A, ES, H>
where
    A: Agent,
    ES: EventStore,
    H: EventHandler<A, ES>,
{
    handler: Handler<AgentState<A>, ES>,
    event_handler: H,
}

impl<A, ES, H> HandlerAdapter<A, ES, H>
where
    A: Agent,
    ES: EventStore,
    H: EventHandler<A, ES>,
{
    pub fn new(handler: Handler<AgentState<A>, ES>, event_handler: H) -> Self {
        Self {
            handler,
            event_handler,
        }
    }
}

impl<A: Agent, ES: EventStore, H: EventHandler<A, ES>> Callback<AgentState<A>>
    for HandlerAdapter<A, ES, H>
{
    async fn process(&mut self, event: &Envelope<AgentState<A>>) -> Result<()> {
        self.event_handler.process(&self.handler, event).await
    }
}

pub struct Runtime<A: Agent + 'static, ES: EventQueue + 'static> {
    pub handler: Handler<AgentState<A>, ES>,
    pub listener: Listener<AgentState<A>, ES>,
}

impl<A: Agent<Services: Clone> + 'static, ES: EventQueue + 'static> Runtime<A, ES> {
    pub fn new(store: ES, services: A::Services) -> Self {
        let listener = store.listener::<AgentState<A>>();
        let handler = Handler::new(store.clone(), services);
        Self { handler, listener }
    }

    pub fn with_handler(mut self, event_handler: impl EventHandler<A, ES> + 'static) -> Self {
        let adapter = HandlerAdapter::new(self.handler.clone(), event_handler);
        self.listener.register(adapter);
        self
    }

    pub async fn start(mut self) -> Result<()> {
        self.listener.run().await
    }
}
