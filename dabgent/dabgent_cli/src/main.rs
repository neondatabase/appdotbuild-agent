use clap::Parser;
use dabgent_cli::{App, agent::Agent};
use dabgent_mq::db::sqlite::SqliteStore;
use sqlx::SqlitePool;
use uuid::Uuid;

#[derive(Parser, Debug)]
#[command(name = "dabgent")]
#[command(about = "Dabgent CLI - AI agent with planning capabilities")]
struct Args {
    #[arg(long, default_value = ":memory:")]
    database: String,

    /// Load environment from .env file
    #[arg(long, default_value = "true")]
    dotenv: bool,
}

#[tokio::main]
async fn main() -> color_eyre::Result<()> {
    // dabgent_cli::agent_ui::demo().await?;
    color_eyre::install()?;

    let args = Args::parse();
    if args.dotenv {
        let _ = dotenvy::dotenv();
    }
    let pool = SqlitePool::connect(&args.database).await?;
    let store = SqliteStore::new(pool);
    store.migrate().await;

    let session_id = Uuid::now_v7();
    let stream_id = format!("{session_id}_session");
    let aggregate_id = format!("{session_id}_cli");

    println!("🚀 Starting Dabgent with Planning Agent");
    println!("📝 Make sure to set ANTHROPIC_API_KEY in your environment");
    println!("🐳 Dagger will be used for sandboxed execution\n");

    let agent = Agent::new(store.clone(), stream_id.clone(), aggregate_id.clone());
    tokio::spawn(agent.run());

    let terminal = ratatui::init();
    let app = App::new(store, stream_id, aggregate_id)?;
    let result = app.run(terminal).await;
    ratatui::restore();
    result
}
