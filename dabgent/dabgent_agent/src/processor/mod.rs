pub mod finish;
pub mod sandbox;
pub mod thread;
pub mod replay;
use dabgent_mq::{EventDb, EventStore, Query};
use std::pin::Pin;
use tokio::sync::mpsc;

pub use finish::FinishProcessor;
pub use sandbox::ToolProcessor;
pub use thread::ThreadProcessor;

pub trait Aggregate: Default {
    type Command;
    type Event;
    type Error: std::error::Error + Send + Sync + 'static;

    fn process(&mut self, command: Self::Command) -> Result<Vec<Self::Event>, Self::Error>;
    fn apply(&mut self, event: &Self::Event);
    fn fold(events: &[Self::Event]) -> Self {
        let mut aggregate = Self::default();
        for event in events {
            aggregate.apply(event);
        }
        aggregate
    }
}

pub trait Processor<T>: Send {
    fn run(&mut self, event: &EventDb<T>) -> impl Future<Output = eyre::Result<()>> + Send;
    fn boxed(self) -> Box<dyn ProcessorDyn<T>>
    where
        Self: Sized + 'static,
    {
        Box::new(self)
    }
}

pub trait ProcessorDyn<T>: Send {
    fn run<'a>(
        &'a mut self,
        event: &'a EventDb<T>,
    ) -> Pin<Box<dyn Future<Output = eyre::Result<()>> + Send + 'a>>;
}

impl<T, P: Processor<T>> ProcessorDyn<T> for P {
    fn run<'a>(
        &'a mut self,
        event: &'a EventDb<T>,
    ) -> Pin<Box<dyn Future<Output = eyre::Result<()>> + Send + 'a>> {
        Box::pin(Processor::run(self, event))
    }
}

pub struct Pipeline<E, T> {
    store: E,
    processors: Vec<Box<dyn ProcessorDyn<T>>>,
}

impl<E, T> Pipeline<E, T>
where
    E: EventStore,
    T: dabgent_mq::Event + std::fmt::Debug + Clone + 'static,
{
    pub fn new(store: E, processors: Vec<Box<dyn ProcessorDyn<T>>>) -> Self {
        Self { store, processors }
    }

    pub async fn run(self, stream_id: String) -> eyre::Result<()> {
        let Self { store, processors } = self;

        let mut set = tokio::task::JoinSet::new();
        let mut senders = Vec::new();
        for mut handler in processors {
            let (tx, mut rx) = mpsc::unbounded_channel();
            set.spawn(async move {
                while let Some(event) = rx.recv().await {
                    if let Err(err) = handler.run(&event).await {
                        tracing::error!("Error processing event: {}", err);
                    }
                }
            });
            senders.push(tx);
        }

        let query = Query::stream(stream_id.clone());
        let mut stream = store.subscribe::<T>(&query)?;
        set.spawn(async move {
            while let Some(event) = stream.next_full().await {
                match event {
                    Ok(event) => {
                        tracing::info!(?event.data, "pipeline");

                        // Check for shutdown event
                        // FixMe: it should be routed by type system, not by string comparison
                        let should_shutdown = event.data.event_type() == "pipeline_shutdown";
                        for sender in senders.iter_mut() {
                            let _ = sender.send(event.clone());
                        }

                        if should_shutdown {
                            tracing::info!("PipelineShutdown event received, terminating pipeline");
                            break;
                        }
                    }
                    Err(err) => {
                        tracing::error!("Error fetching event: {}", err);
                    }
                }
            }
            tracing::info!("Pipeline event loop terminated");
        });
        set.join_all().await;
        Ok(())
    }
}
