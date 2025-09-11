use dabgent_cli::{App, agent::Agent};
use dabgent_mq::db::sqlite::SqliteStore;
use sqlx::SqlitePool;
use uuid::Uuid;

#[tokio::main]
async fn main() -> color_eyre::Result<()> {
    color_eyre::install()?;

    let pool = SqlitePool::connect(":memory:").await?;
    let store = SqliteStore::new(pool);
    store.migrate().await;

    let session_id = Uuid::now_v7();
    let stream_id = format!("{session_id}_session");
    let aggregate_id = format!("{session_id}_cli");

    let agent = Agent::new(store.clone(), stream_id.clone(), aggregate_id.clone());
    tokio::spawn(agent.run());

    let terminal = ratatui::init();
    let app = App::new(store, stream_id, aggregate_id)?;
    let result = app.run(terminal).await;
    ratatui::restore();
    result
}
