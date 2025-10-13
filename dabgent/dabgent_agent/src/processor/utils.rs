use super::agent::{Agent, AgentState};
use dabgent_mq::{Aggregate, Callback, Envelope, Event, EventHandler, EventStore, Handler};
use eyre::Result;
use tokio::sync::oneshot;

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
        tracing::info!(agent = A::TYPE, event = event.data.event_type(), data = ?event.data);
        Ok(())
    }
}

pub struct ShutdownHandler {
    shutdown_tx: Option<oneshot::Sender<()>>,
}

impl ShutdownHandler {
    pub fn new(shutdown_tx: oneshot::Sender<()>) -> Self {
        Self {
            shutdown_tx: Some(shutdown_tx),
        }
    }
}

impl<A: Agent, ES: EventStore> EventHandler<AgentState<A>, ES> for ShutdownHandler {
    async fn process(
        &mut self,
        _handler: &Handler<AgentState<A>, ES>,
        envelope: &Envelope<AgentState<A>>,
    ) -> Result<()> {
        if matches!(&envelope.data, super::agent::Event::Shutdown) {
            tracing::info!("Shutdown event received, triggering graceful shutdown");
            if let Some(tx) = self.shutdown_tx.take() {
                let _ = tx.send(());
            }
        }
        Ok(())
    }
}
