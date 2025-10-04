use crate::llm::CompletionResponse;
use dabgent_mq::{Aggregate, Event as MQEvent};
use eyre::Result;
use rig::message::{ToolCall, ToolResult, UserContent};
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
    Shutdown,
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
    Shutdown,
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
            Event::Shutdown => "shutdown".to_owned(),
            Event::Agent(inner) => inner.event_type(),
        }
    }
}

pub trait Agent: Default + Send + Sync + Clone {
    const TYPE: &'static str;
    type AgentCommand: Send;
    type AgentEvent: MQEvent;
    type AgentError: std::error::Error + Send + Sync + 'static;
    type Services: Send + Sync;

    #[allow(unused)]
    fn handle_tool_results(
        state: &AgentState<Self>,
        services: &Self::Services,
        incoming: Vec<ToolResult>,
    ) -> impl Future<Output = Result<Vec<Event<Self::AgentEvent>>, Self::AgentError>> + Send {
        async move { Ok(vec![state.results_passthrough(&incoming)]) }
    }

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

    pub fn merge_tool_results(&self, incoming: &[ToolResult]) -> Vec<ToolResult> {
        let mut merged = incoming.to_vec();
        merged.extend(self.calls.values().filter_map(|r| r.clone()));
        merged
    }

    pub fn results_passthrough(&self, incoming: &[ToolResult]) -> Event<A::AgentEvent> {
        let completed = self.merge_tool_results(incoming);
        let content = completed.into_iter().map(UserContent::ToolResult);
        let content = rig::OneOrMany::many(content).unwrap();
        Event::UserCompletion { content }
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
            Command::PutUserMessage { content } => {
                if !self.all_tools_ready() {
                    return Err(Error::NotReady.into());
                }
                Ok(vec![Event::UserCompletion { content }])
            }
            Command::PutToolCalls { calls } => Ok(vec![Event::ToolCalls { calls }]),
            Command::PutCompletion { response } => {
                let mut events = vec![Event::AgentCompletion {
                    response: response.clone(),
                }];
                if let Some(calls) = response.tool_calls() {
                    events.push(Event::ToolCalls { calls });
                }
                Ok(events)
            }
            Command::PutToolResults { results } => {
                if let Some(call) = results.iter().find(|c| !self.calls.contains_key(&c.id)) {
                    return Err(Error::UnexpectedTool(call.id.clone()).into());
                }
                let mut events = vec![Event::ToolResults {
                    results: results.clone(),
                }];
                if self.check_ready(&results) {
                    let agent_events = A::handle_tool_results(self, services, results)
                        .await
                        .map_err(AgentError::Agent)?;
                    events.extend(agent_events);
                }
                Ok(events)
            }
            Command::Shutdown => Ok(vec![Event::Shutdown]),
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
            Event::UserCompletion { content } => {
                self.messages.push(rig::message::Message::User {
                    content: content.clone(),
                });
                self.calls.clear();
            }
            Event::ToolCalls { calls } => {
                for call in calls {
                    self.calls.insert(call.id.clone(), None);
                }
            }
            Event::AgentCompletion { response } => {
                self.messages.push(response.message());
            }
            Event::ToolResults { results } => {
                for result in results {
                    self.calls.insert(result.id.clone(), Some(result));
                }
            }
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
