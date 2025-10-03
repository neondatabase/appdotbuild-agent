use dabgent_mq::{Aggregate, Envelope, EventHandler, EventQueue, EventStore, Handler, Listener};
use eyre::Result;

/// Link trait for bidirectional communication between two aggregates.
pub trait Link<ES: EventStore>: Send + Sync {
    type AggregateA: Aggregate<Command: Send, Services: Clone> + Clone;
    type AggregateB: Aggregate<Command: Send, Services: Clone> + Clone;

    fn forward(
        &self,
        event: &Envelope<Self::AggregateA>,
        handler: &Handler<Self::AggregateA, ES>,
    ) -> impl Future<Output = Option<(String, <Self::AggregateB as Aggregate>::Command)>> + Send;

    fn backward(
        &self,
        event: &Envelope<Self::AggregateB>,
        handler: &Handler<Self::AggregateB, ES>,
    ) -> impl Future<Output = Option<(String, <Self::AggregateA as Aggregate>::Command)>> + Send;
}

struct ForwardLinkHandler<ES, L>
where
    ES: EventStore,
    L: Link<ES>,
{
    handler_b: Handler<L::AggregateB, ES>,
    link: L,
}

impl<ES, L> EventHandler<L::AggregateA, ES> for ForwardLinkHandler<ES, L>
where
    ES: EventStore,
    L: Link<ES>,
{
    async fn process(
        &mut self,
        handler: &Handler<L::AggregateA, ES>,
        envelope: &Envelope<L::AggregateA>,
    ) -> Result<()> {
        if let Some((aggregate_id, command)) = self.link.forward(&envelope, handler).await {
            self.handler_b
                .execute_with_metadata(&aggregate_id, command, envelope.metadata.clone())
                .await?;
        }
        Ok(())
    }
}

struct BackwardLinkHandler<ES, L>
where
    ES: EventStore,
    L: Link<ES>,
{
    handler_a: Handler<L::AggregateA, ES>,
    link: L,
}

impl<ES, L> EventHandler<L::AggregateB, ES> for BackwardLinkHandler<ES, L>
where
    ES: EventStore,
    L: Link<ES>,
{
    async fn process(
        &mut self,
        handler: &Handler<L::AggregateB, ES>,
        envelope: &Envelope<L::AggregateB>,
    ) -> Result<()> {
        if let Some((aggregate_id, command)) = self.link.backward(&envelope, &handler).await {
            self.handler_a
                .execute_with_metadata(&aggregate_id, command, envelope.metadata.clone())
                .await?;
        }
        Ok(())
    }
}

pub struct Runtime<A: Aggregate + 'static, ES: EventQueue + 'static> {
    pub handler: Handler<A, ES>,
    pub listener: Listener<A, ES>,
    pub services: A::Services,
}

impl<A: Aggregate<Services: Clone> + 'static, ES: EventQueue + 'static> Runtime<A, ES> {
    pub fn new(store: ES, services: A::Services) -> Self {
        let listener = store.listener::<A>();
        let handler = Handler::new(store.clone(), services.clone());
        Self {
            handler,
            listener,
            services,
        }
    }

    pub fn with_handler(mut self, handler: impl EventHandler<A, ES> + 'static) -> Self {
        self.listener.push_handler(handler, self.services.clone());
        self
    }

    pub async fn start(mut self) -> Result<()> {
        self.listener.run().await
    }
}

pub fn link_runtimes<ES, L>(
    runtime_a: &mut Runtime<L::AggregateA, ES>,
    runtime_b: &mut Runtime<L::AggregateB, ES>,
    link: L,
) where
    ES: EventQueue + 'static,
    L: Link<ES> + Clone + 'static,
{
    let forward_handler = ForwardLinkHandler {
        handler_b: runtime_b.handler.clone(),
        link: link.clone(),
    };

    let backward_handler = BackwardLinkHandler {
        handler_a: runtime_a.handler.clone(),
        link,
    };

    runtime_a
        .listener
        .push_handler(forward_handler, runtime_a.services.clone());
    runtime_b
        .listener
        .push_handler(backward_handler, runtime_b.services.clone());
}
