use crate::db::{postgres::PostgresStore, sqlite::SqliteStore, *};
use eyre::Result;
use sqlx::{PgPool, SqlitePool};

#[derive(Clone)]
pub enum AnyStore {
    Postgres(PostgresStore),
    Sqlite(SqliteStore),
}

impl EventStore for AnyStore {
    async fn push_event<T: crate::models::Event>(
        &self,
        stream_id: &str,
        aggregate_id: &str,
        event: &T,
        metadata: &Metadata,
    ) -> Result<(), Error> {
        match self {
            AnyStore::Postgres(store) => store.push_event(stream_id, aggregate_id, event, metadata).await,
            AnyStore::Sqlite(store) => store.push_event(stream_id, aggregate_id, event, metadata).await,
        }
    }

    async fn load_events_raw(
        &self,
        query: &Query,
        sequence: Option<i64>,
    ) -> Result<Vec<Event<serde_json::Value>>, Error> {
        match self {
            AnyStore::Postgres(store) => store.load_events_raw(query, sequence).await,
            AnyStore::Sqlite(store) => store.load_events_raw(query, sequence).await,
        }
    }

    fn get_watchers(&self) -> &std::sync::Arc<std::sync::Mutex<std::collections::HashMap<Query, Vec<tokio::sync::mpsc::UnboundedSender<Event<serde_json::Value>>>>>> {
        match self {
            AnyStore::Postgres(store) => store.get_watchers(),
            AnyStore::Sqlite(store) => store.get_watchers(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct StoreConfig {
    pub wipe_on_start: bool,
}

impl Default for StoreConfig {
    fn default() -> Self {
        Self {
            wipe_on_start: false,
        }
    }
}

impl StoreConfig {
    pub fn with_wipe(mut self, wipe: bool) -> Self {
        self.wipe_on_start = wipe;
        self
    }

    pub fn from_env() -> Self {
        let wipe_on_start = std::env::var("WIPE_DATABASE")
            .map(|v| v.to_lowercase() == "true" || v == "1")
            .unwrap_or(false);

        Self { wipe_on_start }
    }
}

pub async fn create_store(config: Option<StoreConfig>) -> Result<AnyStore> {
    let config = config.unwrap_or_else(StoreConfig::from_env);

    if let Ok(postgres_url) = std::env::var("POSTGRES_URL") {
        tracing::info!("Using PostgreSQL store with URL: {}", mask_password(&postgres_url));

        let pool = PgPool::connect(&postgres_url).await?;

        if config.wipe_on_start {
            tracing::warn!("Wiping PostgreSQL database for debug run...");
            wipe_postgres_database(&pool).await?;
        }

        let store = PostgresStore::new(pool);
        store.migrate().await;
        tracing::info!("PostgreSQL store initialized successfully");

        Ok(AnyStore::Postgres(store))
    } else {
        tracing::info!("No POSTGRES_URL found, using in-memory SQLite store");

        let pool = SqlitePool::connect(":memory:").await?;
        let store = SqliteStore::new(pool);
        store.migrate().await;
        tracing::info!("SQLite store initialized successfully");

        Ok(AnyStore::Sqlite(store))
    }
}

async fn wipe_postgres_database(pool: &PgPool) -> Result<()> {
    // Drop events table and migration tracking
    sqlx::query("DROP TABLE IF EXISTS events CASCADE")
        .execute(pool)
        .await?;

    sqlx::query("DROP TABLE IF EXISTS _sqlx_migrations CASCADE")
        .execute(pool)
        .await?;

    tracing::info!("PostgreSQL database wiped successfully");
    Ok(())
}

fn mask_password(url: &str) -> String {
    if let Ok(mut parsed) = url::Url::parse(url) {
        if parsed.password().is_some() {
            let _ = parsed.set_password(Some("***"));
        }
        parsed.to_string()
    } else {
        // fallback for malformed URLs
        url.to_string()
    }
}
