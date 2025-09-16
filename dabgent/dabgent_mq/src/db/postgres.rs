use crate::db::*;
use chrono::Utc;
use serde_json::Value as JsonValue;
use sqlx::PgPool;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use tokio::sync::mpsc;

static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations/postgres");

#[derive(Clone)]
pub struct PostgresStore {
    pool: PgPool,
    watchers: Arc<Mutex<HashMap<Query, Vec<mpsc::UnboundedSender<Event<JsonValue>>>>>>,
}

impl PostgresStore {
    pub fn new(pool: PgPool) -> Self {
        Self {
            pool,
            watchers: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    fn build_query(query: &Query, last_sequence: Option<i64>) -> (String, Vec<String>) {
        let mut conditions = vec!["stream_id = $1".to_string()];
        let mut params = vec![query.stream_id.clone()];
        let mut param_counter = 2;

        if let Some(event_type) = &query.event_type {
            conditions.push(format!("event_type = ${param_counter}"));
            params.push(event_type.clone());
            param_counter += 1;
        }

        if let Some(aggregate_id) = &query.aggregate_id {
            conditions.push(format!("aggregate_id = ${param_counter}"));
            params.push(aggregate_id.clone());
            param_counter += 1;
        }

        if let Some(last_seq) = last_sequence {
            conditions.push(format!("sequence > ${param_counter}"));
            params.push(last_seq.to_string());
        }

        let where_clause = conditions.join(" AND ");
        let sql = format!("SELECT * FROM events WHERE {where_clause} ORDER BY sequence ASC");
        (sql, params)
    }
}

impl PostgresStore {
    pub async fn migrate(&self) {
        MIGRATOR.run(&self.pool).await.expect("Migration failed")
    }
}

impl EventStore for PostgresStore {
    async fn push_event<T: models::Event>(
        &self,
        stream_id: &str,
        aggregate_id: &str,
        event: &T,
        metadata: &Metadata,
    ) -> Result<(), Error> {
        let event_data = serde_json::to_value(event).map_err(Error::Serialization)?;
        let metadata_json = serde_json::to_value(metadata).map_err(Error::Serialization)?;

        let mut tx = self.pool.begin().await.map_err(Error::Database)?;

        let next_sequence: i64 = sqlx::query_scalar(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE stream_id = $1",
        )
        .bind(stream_id)
        .fetch_one(&mut *tx)
        .await
        .map_err(Error::Database)?;

        sqlx::query(
            r#"
            INSERT INTO events (stream_id, event_type, aggregate_id, sequence, event_version, data, metadata, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            "#
        )
        .bind(stream_id)
        .bind(event.event_type())
        .bind(aggregate_id)
        .bind(next_sequence)
        .bind(T::EVENT_VERSION)
        .bind(event_data)
        .bind(metadata_json)
        .bind(Utc::now())
        .execute(&mut *tx)
        .await
        .map_err(Error::Database)?;

        tx.commit().await.map_err(Error::Database)?;

        Ok(())
    }

    async fn load_events_raw(
        &self,
        query: &Query,
        sequence: Option<i64>,
    ) -> Result<Vec<Event<JsonValue>>, Error> {
        let (sql, params) = Self::build_query(query, sequence);
        let mut sqlx_query = sqlx::query_as::<_, Event<JsonValue>>(&sql);
        for param in params.iter() {
            sqlx_query = sqlx_query.bind(param);
        }
        let events = sqlx_query
            .fetch_all(&self.pool)
            .await
            .map_err(Error::Database)?;
        Ok(events)
    }

    fn get_watchers(
        &self,
    ) -> &Arc<Mutex<HashMap<Query, Vec<mpsc::UnboundedSender<Event<JsonValue>>>>>> {
        &self.watchers
    }
}
