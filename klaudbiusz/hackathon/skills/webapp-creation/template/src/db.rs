use sqlx::{Pool, Postgres, postgres::PgPoolOptions};
use std::env;

pub type DbPool = Pool<Postgres>;

pub async fn init_pool() -> Result<DbPool, Box<dyn std::error::Error>> {
    // load .env file if present (ignored if missing)
    let _ = dotenvy::dotenv();

    let database_url = env::var("DATABASE_URL")
        .map_err(|_| "DATABASE_URL environment variable must be set")?;

    let pool = PgPoolOptions::new()
        .max_connections(5)
        .connect(&database_url)
        .await
        .map_err(|e| format!("failed to connect to database: {e}"))?;

    Ok(pool)
}
