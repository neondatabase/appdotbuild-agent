use crate::EventStore;
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use std::fmt;

pub trait Event: Serialize + for<'de> Deserialize<'de> + Clone + fmt::Debug + Send + Sync {
    fn event_type(&self) -> String;
    fn event_version(&self) -> String;
}

pub trait Aggregate: Default + Send {
    const TYPE: &'static str;
    type Command;
    type Event: Event;
    type Error: std::error::Error + Send + Sync + 'static;
    type Services: Send + Sync;

    fn handle(
        &self,
        cmd: Self::Command,
        services: &Self::Services,
    ) -> impl Future<Output = Result<Vec<Self::Event>, Self::Error>> + Send;

    fn apply(&mut self, event: Self::Event);

    fn fold(events: Vec<Self::Event>) -> Self {
        events
            .into_iter()
            .fold(Default::default(), |mut acc, event| {
                acc.apply(event);
                acc
            })
    }
}

#[derive(Clone)]
pub struct Handler<A: Aggregate, ES: EventStore> {
    store: ES,
    services: A::Services,
}

impl<A: Aggregate, ES: EventStore> Handler<A, ES> {
    pub fn new(store: ES, services: A::Services) -> Self {
        Self { store, services }
    }

    pub fn store(&self) -> &ES {
        &self.store
    }

    pub async fn execute(&self, aggregate_id: &str, cmd: A::Command) -> eyre::Result<()> {
        self.execute_with_metadata(aggregate_id, cmd, Default::default())
            .await
    }

    pub async fn execute_with_metadata(
        &self,
        aggregate_id: &str,
        cmd: A::Command,
        metadata: Metadata,
    ) -> eyre::Result<()> {
        let ctx = self.store.load_aggregate::<A>(aggregate_id).await?;
        let events = ctx.aggregate.handle(cmd, &self.services).await?;
        self.store.commit(events, metadata, ctx).await?;
        Ok(())
    }

    pub async fn load_aggregate(&self, aggregate_id: &str) -> eyre::Result<A> {
        let ctx = self.store.load_aggregate::<A>(aggregate_id).await?;
        Ok(ctx.aggregate)
    }

    pub async fn load_events(&self, aggregate_id: &str) -> eyre::Result<Vec<A::Event>> {
        let events = self.store.load_events::<A>(aggregate_id).await?;
        Ok(events.into_iter().map(|event| event.data).collect())
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Envelope<A: Aggregate> {
    pub aggregate_id: String,
    pub sequence: i64,
    pub data: A::Event,
    pub metadata: Metadata,
}

impl<A: Aggregate> Clone for Envelope<A> {
    fn clone(&self) -> Self {
        Self {
            aggregate_id: self.aggregate_id.clone(),
            sequence: self.sequence,
            data: self.data.clone(),
            metadata: self.metadata.clone(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AggregateContext<A: Aggregate> {
    pub aggregate_id: String,
    pub aggregate: A,
    pub current_sequence: i64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Metadata {
    pub correlation_id: Option<uuid::Uuid>,
    pub causation_id: Option<uuid::Uuid>,
    pub extra: Option<JsonValue>,
}

impl Metadata {
    pub fn new(
        correlation_id: Option<uuid::Uuid>,
        causation_id: Option<uuid::Uuid>,
        extra: Option<JsonValue>,
    ) -> Self {
        Metadata {
            correlation_id,
            causation_id,
            extra,
        }
    }

    pub fn with_correlation_id(mut self, correlation_id: uuid::Uuid) -> Self {
        self.correlation_id = Some(correlation_id);
        self
    }

    pub fn with_causation_id(mut self, causation_id: uuid::Uuid) -> Self {
        self.causation_id = Some(causation_id);
        self
    }

    pub fn with_extra(mut self, extra: JsonValue) -> Self {
        self.extra = Some(extra);
        self
    }
}
