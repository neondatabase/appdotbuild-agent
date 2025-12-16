mod auth;
mod db;
mod models;

use axum::{
    Router,
    middleware,
    routing::get,
    response::{Html, IntoResponse, Response},
    extract::State,
    http::StatusCode,
};
use askama::Template;
use tower_http::{services::ServeDir, trace::TraceLayer};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use db::DbPool;

// error handling - allows handlers to return Result<T, AppError>
#[derive(Debug)]
struct AppError(String);

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        tracing::error!("handler error: {}", self.0);
        (StatusCode::INTERNAL_SERVER_ERROR, self.0).into_response()
    }
}

impl<E: std::error::Error> From<E> for AppError {
    fn from(err: E) -> Self {
        AppError(err.to_string())
    }
}

#[derive(Template)]
#[template(path = "index.html")]
struct IndexTemplate {
    // add your data here, e.g.:
    // items: Vec<models::Item>,
}

#[derive(Template)]
#[template(path = "create.html")]
struct CreateTemplate;

#[allow(dead_code)]
#[derive(Template)]
#[template(path = "edit.html")]
struct EditTemplate {
    // item: models::Item,
}

#[derive(Clone)]
struct AppState {
    #[allow(dead_code)]
    pool: DbPool,
}

async fn index(State(_state): State<AppState>) -> Result<Html<String>, AppError> {
    // example: fetch items from db
    // let items = sqlx::query_as::<_, models::Item>("SELECT * FROM items")
    //     .fetch_all(&state.pool)
    //     .await?;

    let template = IndexTemplate {
        // items,
    };
    Ok(Html(template.render()?))
}

async fn new_form() -> Result<Html<String>, AppError> {
    let template = CreateTemplate;
    Ok(Html(template.render()?))
}

// example route handlers - uncomment and modify as needed
//
// async fn create(
//     State(state): State<AppState>,
//     Form(input): Form<models::CreateItem>,
// ) -> Result<impl IntoResponse, AppError> {
//     sqlx::query("INSERT INTO items (name) VALUES ($1)")
//         .bind(&input.name)
//         .execute(&state.pool)
//         .await?;
//     Ok(Redirect::to("/"))
// }
//
// async fn edit_form(
//     State(state): State<AppState>,
//     Path(id): Path<i64>,
// ) -> Result<Html<String>, AppError> {
//     let item = sqlx::query_as::<_, models::Item>("SELECT * FROM items WHERE id = $1")
//         .bind(id)
//         .fetch_one(&state.pool)
//         .await?;
//     let template = EditTemplate { item };
//     Ok(Html(template.render()?))
// }
//
// async fn update(
//     State(state): State<AppState>,
//     Path(id): Path<i64>,
//     Form(input): Form<models::UpdateItem>,
// ) -> Result<impl IntoResponse, AppError> {
//     // build dynamic update query based on provided fields
//     if let Some(name) = input.name {
//         sqlx::query("UPDATE items SET name = $1 WHERE id = $2")
//             .bind(&name)
//             .bind(id)
//             .execute(&state.pool)
//             .await?;
//     }
//     Ok(Redirect::to("/"))
// }
//
// async fn delete(
//     State(state): State<AppState>,
//     Path(id): Path<i64>,
// ) -> Result<Html<&'static str>, AppError> {
//     sqlx::query("DELETE FROM items WHERE id = $1")
//         .bind(id)
//         .execute(&state.pool)
//         .await?;
//     Ok(Html("")) // htmx will remove the row
// }

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::registry()
        .with(tracing_subscriber::fmt::layer())
        .with(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    let pool = db::init_pool().await?;

    // run migrations
    sqlx::migrate!("./migrations")
        .run(&pool)
        .await
        .map_err(|e| format!("failed to run migrations: {e}"))?;

    let state = AppState { pool };

    let app = Router::new()
        .route("/", get(index))
        .route("/new", get(new_form))
        // uncomment as you add handlers:
        // .route("/", post(create))
        // .route("/{id}/edit", get(edit_form))
        // .route("/{id}", put(update).delete(delete))
        .nest_service("/static", ServeDir::new("static"))
        .layer(TraceLayer::new_for_http())
        .layer(middleware::from_fn_with_state(
            state.pool.clone(),
            auth::auth_middleware,
        ))
        .with_state(state);

    let port = std::env::var("PORT").unwrap_or_else(|_| "8000".to_string());
    let addr = format!("0.0.0.0:{port}");
    tracing::info!("listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(&addr)
        .await
        .map_err(|e| format!("failed to bind to {addr}: {e}"))?;
    axum::serve(listener, app)
        .await
        .map_err(|e| format!("server error: {e}"))?;

    Ok(())
}
