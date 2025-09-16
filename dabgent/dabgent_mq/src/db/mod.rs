pub mod postgres;
pub mod sqlite;
use crate::models::{self};
use chrono::{DateTime, Utc};
use eyre::Result;
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::sync::mpsc;

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct Event<T> {
    pub stream_id: String,
    pub event_type: String,
    pub aggregate_id: String,
    pub sequence: i64,
    pub event_version: String,
    pub data: T,
    pub metadata: JsonValue,
    pub created_at: DateTime<Utc>,
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

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct Query {
    pub stream_id: String,
    pub event_type: Option<String>,
    pub aggregate_id: Option<String>,
}

type SubscriberMap<T> = HashMap<Query, Vec<mpsc::UnboundedSender<T>>>;

pub trait EventStore: Clone + Send + Sync + 'static {
    fn push_event<T: models::Event>(
        &self,
        stream_id: &str,
        aggregate_id: &str,
        event: &T,
        metadata: &Metadata,
    ) -> impl Future<Output = Result<(), Error>> + Send;

    fn load_events<T: models::Event>(
        &self,
        query: &Query,
        sequence: Option<i64>,
    ) -> impl Future<Output = Result<Vec<T>, Error>> + Send {
        async move {
            let events = self.load_events_raw(query, sequence).await?;
            events
                .into_iter()
                .map(|row| serde_json::from_value::<T>(row.data).map_err(Error::Serialization))
                .collect::<Result<Vec<T>, Error>>()
        }
    }

    fn load_events_raw(
        &self,
        query: &Query,
        sequence: Option<i64>,
    ) -> impl Future<Output = Result<Vec<Event<JsonValue>>, Error>> + Send;

    fn get_watchers(&self) -> &Arc<Mutex<SubscriberMap<Event<JsonValue>>>>;

    fn subscribe<T: models::Event + 'static>(
        &self,
        query: &Query,
    ) -> Result<EventStream<T>, Error> {
        let mut watchers = self.get_watchers().lock().unwrap();
        let (event_tx, event_rx) = mpsc::unbounded_channel();

        let senders = watchers.entry(query.clone()).or_insert_with(|| {
            let store = self.clone();
            let query = query.clone();
            let watchers_arc = self.get_watchers().clone();

            tokio::spawn(async move {
                let mut offset = 0i64;
                const POLL_INTERVAL: Duration = Duration::from_millis(500);

                loop {
                    let events = match store.load_events_raw(&query, Some(offset)).await {
                        Ok(events) => events,
                        Err(err) => {
                            tracing::error!(?err, "error loading events");
                            return;
                        }
                    };
                    for event in events {
                        let mut watchers = watchers_arc.lock().unwrap();
                        match watchers.get_mut(&query) {
                            Some(senders) => {
                                senders.retain(|tx| tx.send(event.clone()).is_ok());
                                if senders.is_empty() {
                                    watchers.remove(&query);
                                }
                            }
                            None => return,
                        }
                        offset = offset.max(event.sequence);
                    }
                    tokio::time::sleep(POLL_INTERVAL).await;
                }
            });

            Vec::new()
        });

        senders.push(event_tx);

        Ok(EventStream::new(event_rx))
    }
}

impl Event<JsonValue> {
    pub fn from_value<T: serde::de::DeserializeOwned>(self) -> Result<Event<T>, Error> {
        let data = serde_json::from_value::<T>(self.data).map_err(Error::Serialization)?;
        Ok(Event {
            stream_id: self.stream_id,
            event_type: self.event_type,
            aggregate_id: self.aggregate_id,
            sequence: self.sequence,
            event_version: self.event_version,
            metadata: self.metadata,
            created_at: self.created_at,
            data,
        })
    }
}

pub struct EventStream<T: models::Event> {
    rx: mpsc::UnboundedReceiver<Event<JsonValue>>,
    _marker: std::marker::PhantomData<T>,
}

impl<T: models::Event> EventStream<T> {
    pub fn new(rx: mpsc::UnboundedReceiver<Event<JsonValue>>) -> Self {
        Self {
            rx,
            _marker: std::marker::PhantomData,
        }
    }

    pub async fn next(&mut self) -> Option<Result<T, Error>> {
        self.next_full().await.map(|r| r.map(|e| e.data))
    }

    pub async fn next_full(&mut self) -> Option<Result<Event<T>, Error>> {
        self.rx.recv().await.map(Event::from_value)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("Database error: {0}")]
    Database(sqlx::Error),
    #[error("Serialization error: {0}")]
    Serialization(serde_json::Error),
}
