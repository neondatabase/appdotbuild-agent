use crate::db::{postgres::PostgresStore, sqlite::SqliteStore, EventStore};
use crate::{Aggregate, AggregateContext, Envelope, Metadata};
use eyre::Result;
use sqlx::{PgPool, SqlitePool};

#[derive(Clone)]
pub enum AnyStore {
    Postgres(PostgresStore),
    Sqlite(SqliteStore),
}

impl EventStore for AnyStore {
    async fn commit<A: Aggregate>(
        &self,
        events: Vec<A::Event>,
        metadata: Metadata,
        context: AggregateContext<A>,
    ) -> Result<Vec<Envelope<A>>, crate::db::Error> {
        match self {
            AnyStore::Postgres(store) => store.commit(events, metadata, context).await,
            AnyStore::Sqlite(store) => store.commit(events, metadata, context).await,
        }
    }

    async fn load_events<A: Aggregate>(
        &self,
        aggregate_id: &str,
    ) -> Result<Vec<Envelope<A>>, crate::db::Error> {
        match self {
            AnyStore::Postgres(store) => store.load_events(aggregate_id).await,
            AnyStore::Sqlite(store) => store.load_events(aggregate_id).await,
        }
    }

    async fn load_latest_events<A: Aggregate>(
        &self,
        aggregate_id: &str,
        sequence_from: i64,
    ) -> Result<Vec<Envelope<A>>, crate::db::Error> {
        match self {
            AnyStore::Postgres(store) => store.load_latest_events(aggregate_id, sequence_from).await,
            AnyStore::Sqlite(store) => store.load_latest_events(aggregate_id, sequence_from).await,
        }
    }

    async fn load_aggregate<A: Aggregate>(
        &self,
        aggregate_id: &str,
    ) -> Result<AggregateContext<A>, crate::db::Error> {
        match self {
            AnyStore::Postgres(store) => store.load_aggregate(aggregate_id).await,
            AnyStore::Sqlite(store) => store.load_aggregate(aggregate_id).await,
        }
    }

    async fn load_sequence_nums<A: Aggregate>(
        &self,
    ) -> Result<Vec<(String, i64)>, crate::db::Error> {
        match self {
            AnyStore::Postgres(store) => store.load_sequence_nums::<A>().await,
            AnyStore::Sqlite(store) => store.load_sequence_nums::<A>().await,
        }
    }
}

#[derive(Debug, Clone)]
pub struct StoreConfig {
    pub stream_id: String,
    pub wipe_on_start: bool,
}

impl Default for StoreConfig {
    fn default() -> Self {
        Self {
            stream_id: "default".to_string(),
            wipe_on_start: false,
        }
    }
}

impl StoreConfig {
    pub fn with_wipe(mut self, wipe: bool) -> Self {
        self.wipe_on_start = wipe;
        self
    }

    pub fn with_stream_id(mut self, stream_id: String) -> Self {
        self.stream_id = stream_id;
        self
    }

    pub fn from_env() -> Self {
        let wipe_on_start = std::env::var("WIPE_DATABASE")
            .map(|v| v.to_lowercase() == "true" || v == "1")
            .unwrap_or(false);

        let stream_id = std::env::var("STREAM_ID").unwrap_or_else(|_| "default".to_string());

        Self {
            stream_id,
            wipe_on_start,
        }
    }
}

pub async fn create_store(config: Option<StoreConfig>) -> Result<AnyStore> {
    let config = config.unwrap_or_else(StoreConfig::from_env);

    if let Ok(postgres_url) = std::env::var("POSTGRES_URL") {
        tracing::info!(
            "Using PostgreSQL store with URL: {}, stream_id: {}",
            mask_password(&postgres_url),
            config.stream_id
        );

        let pool = PgPool::connect(&postgres_url).await?;

        if config.wipe_on_start {
            tracing::warn!("Wiping PostgreSQL database...");
            wipe_postgres_database(&pool).await?;
        }

        let store = PostgresStore::new(pool, &config.stream_id);
        store.migrate().await;
        tracing::info!("PostgreSQL store initialized successfully");

        Ok(AnyStore::Postgres(store))
    } else {
        tracing::info!(
            "No POSTGRES_URL found, using in-memory SQLite store with stream_id: {}",
            config.stream_id
        );

        let pool = SqlitePool::connect(":memory:").await?;
        let store = SqliteStore::new(pool, &config.stream_id);
        store.migrate().await;
        tracing::info!("SQLite store initialized successfully");

        Ok(AnyStore::Sqlite(store))
    }
}

async fn wipe_postgres_database(pool: &PgPool) -> Result<()> {
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
        url.to_string()
    }
}
