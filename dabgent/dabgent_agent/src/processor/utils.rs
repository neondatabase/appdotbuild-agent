use super::agent::{Agent, AgentState};
use dabgent_mq::{Aggregate, Callback, Envelope, Event, EventHandler, EventStore, Handler};
use eyre::Result;

pub struct LogHandler;

impl<T: Aggregate + std::fmt::Debug> Callback<T> for LogHandler {
    async fn process(&mut self, envelope: &Envelope<T>) -> Result<()> {
        tracing::info!(aggregate = T::TYPE, envelope = ?envelope, "event");
        Ok(())
    }
}

impl<A: Agent, ES: EventStore> EventHandler<AgentState<A>, ES> for LogHandler
where
    AgentState<A>: std::fmt::Debug,
{
    async fn process(
        &mut self,
        _handler: &Handler<AgentState<A>, ES>,
        event: &Envelope<AgentState<A>>,
    ) -> Result<()> {
        // tracing::info!(agent = A::TYPE, envelope = ?event, "event");
        tracing::info!(agent = A::TYPE, event = event.data.event_type(), data = ?event.data);
        Ok(())
    }
}
