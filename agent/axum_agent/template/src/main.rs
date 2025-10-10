use axum::{
    http::StatusCode,
    response::{Html, IntoResponse},
    routing::get,
    Router,
};
use diesel::r2d2::{ConnectionManager, Pool};
use diesel::{Connection, PgConnection};
use diesel_migrations::{embed_migrations, EmbeddedMigrations, MigrationHarness};
use std::sync::Arc;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;
use tracing_subscriber;

pub mod config;
pub mod error;
pub mod http;
pub mod models;
pub mod schema;
pub mod services;

use config::Config;
use error::AppError;

const MIGRATIONS: EmbeddedMigrations = embed_migrations!("migrations/");

pub type DbPool = Pool<ConnectionManager<PgConnection>>;

#[derive(Clone)]
pub struct AppState {
    pub db: DbPool,
    pub config: Arc<Config>,
}

impl AppState {
    pub async fn new() -> Result<Self, AppError> {
        let config = Config::from_env()?;
        let db = create_db_pool(&config.database_url)?;
        
        Ok(Self {
            db,
            config: Arc::new(config),
        })
    }
}

pub fn create_db_pool(database_url: &str) -> Result<DbPool, AppError> {
    let manager = ConnectionManager::<PgConnection>::new(database_url);
    let pool = Pool::builder()
        .max_size(10)
        .min_idle(Some(2))
        .build(manager)
        .map_err(|e| AppError::DatabaseConnectionError(e.to_string()))?;
    
    Ok(pool)
}

async fn health() -> impl IntoResponse {
    (StatusCode::OK, "healthy")
}

async fn index() -> impl IntoResponse {
    let html = r#"
    <!DOCTYPE html>
    <html>
    <head>
        <title>Axum + HTMX + Diesel App</title>
        <script src="https://unpkg.com/htmx.org@1.9.10"></script>
        <style>
            body { 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                margin: 0; 
                padding: 2rem; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                color: white;
            }
            .container { 
                max-width: 800px; 
                margin: 0 auto; 
                text-align: center;
            }
            .card {
                background: rgba(255, 255, 255, 0.1);
                backdrop-filter: blur(10px);
                border-radius: 20px;
                padding: 2rem;
                border: 1px solid rgba(255, 255, 255, 0.2);
            }
            h1 { font-size: 3rem; margin-bottom: 1rem; }
            .subtitle { font-size: 1.2rem; opacity: 0.9; margin-bottom: 2rem; }
            .features {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 1rem;
                margin-top: 2rem;
            }
            .feature {
                background: rgba(255, 255, 255, 0.05);
                padding: 1rem;
                border-radius: 10px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>🚀 Welcome to your Rust App</h1>
                <p class="subtitle">Built with Axum + HTMX + Diesel</p>
                
                <div class="features">
                    <div class="feature">
                        <h3>⚡ Axum 0.8</h3>
                        <p>Modern async web framework</p>
                    </div>
                    <div class="feature">
                        <h3>🎯 HTMX</h3>
                        <p>Dynamic interactions without JS</p>
                    </div>
                    <div class="feature">
                        <h3>🗄️ Diesel</h3>
                        <p>Type-safe ORM for PostgreSQL</p>
                    </div>
                    <div class="feature">
                        <h3>🔒 Secure</h3>
                        <p>Built-in auth & validation</p>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    "#;
    Html(html)
}

fn run_migrations(connection: &mut PgConnection) -> Result<(), Box<dyn std::error::Error + Send + Sync + 'static>> {
    connection.run_pending_migrations(MIGRATIONS)?;
    Ok(())
}

pub fn create_router(state: AppState) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/health", get(health))
        .route("/healthcheck", get(health))
        .merge(http::routes::api_routes())
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http())
        .with_state(state)
}

#[tokio::main]
async fn main() -> Result<(), AppError> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    // Load configuration
    dotenvy::dotenv().ok();
    let state = AppState::new().await?;

    // Run migrations
    let mut conn = PgConnection::establish(&state.config.database_url)
        .map_err(|e| AppError::DatabaseConnectionError(e.to_string()))?;
    run_migrations(&mut conn)
        .map_err(|e| AppError::MigrationError(e.to_string()))?;

    // Create application
    let app = create_router(state.clone());

    let addr = format!("{}:{}", state.config.host, state.config.port);
    let listener = tokio::net::TcpListener::bind(&addr).await
        .map_err(|e| AppError::ServerStartError(e.to_string()))?;
    
    tracing::info!("Server running on http://{}", addr);
    
    axum::serve(listener, app).await
        .map_err(|e| AppError::ServerStartError(e.to_string()))?;
    
    Ok(())
}