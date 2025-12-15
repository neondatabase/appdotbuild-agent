mod db;
mod models;

use axum::{
    Router,
    routing::get,
    response::Html,
    extract::State,
};
use askama::Template;
use tower_http::services::ServeDir;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use db::DbPool;

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

async fn index(State(_state): State<AppState>) -> Html<String> {
    // example: fetch items from db
    // let items = sqlx::query_as::<_, models::Item>("SELECT * FROM items")
    //     .fetch_all(&state.pool)
    //     .await
    //     .unwrap_or_default();

    let template = IndexTemplate {
        // items,
    };
    Html(template.render().expect("template render failed"))
}

async fn new_form() -> Html<String> {
    let template = CreateTemplate;
    Html(template.render().expect("template render failed"))
}

// example route handlers - uncomment and modify as needed
//
// async fn create(
//     State(state): State<AppState>,
//     Form(input): Form<models::CreateItem>,
// ) -> impl IntoResponse {
//     sqlx::query("INSERT INTO items (name) VALUES ($1)")
//         .bind(&input.name)
//         .execute(&state.pool)
//         .await
//         .expect("insert failed");
//     Redirect::to("/")
// }
//
// async fn edit_form(
//     State(state): State<AppState>,
//     Path(id): Path<i64>,
// ) -> Html<String> {
//     let item = sqlx::query_as::<_, models::Item>("SELECT * FROM items WHERE id = $1")
//         .bind(id)
//         .fetch_one(&state.pool)
//         .await
//         .expect("item not found");
//     let template = EditTemplate { item };
//     Html(template.render().expect("template render failed"))
// }
//
// async fn update(
//     State(state): State<AppState>,
//     Path(id): Path<i64>,
//     Form(input): Form<models::UpdateItem>,
// ) -> impl IntoResponse {
//     // build dynamic update query based on provided fields
//     if let Some(name) = input.name {
//         sqlx::query("UPDATE items SET name = $1 WHERE id = $2")
//             .bind(&name)
//             .bind(id)
//             .execute(&state.pool)
//             .await
//             .expect("update failed");
//     }
//     Redirect::to("/")
// }
//
// async fn delete(
//     State(state): State<AppState>,
//     Path(id): Path<i64>,
// ) -> impl IntoResponse {
//     sqlx::query("DELETE FROM items WHERE id = $1")
//         .bind(id)
//         .execute(&state.pool)
//         .await
//         .expect("delete failed");
//     Html("") // htmx will remove the row
// }

#[tokio::main]
async fn main() {
    tracing_subscriber::registry()
        .with(tracing_subscriber::fmt::layer())
        .with(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    let pool = db::init_pool().await;

    // run migrations
    sqlx::migrate!("./migrations")
        .run(&pool)
        .await
        .expect("migrations failed");

    let state = AppState { pool };

    let app = Router::new()
        .route("/", get(index))
        .route("/new", get(new_form))
        // uncomment as you add handlers:
        // .route("/", post(create))
        // .route("/{id}/edit", get(edit_form))
        // .route("/{id}", put(update).delete(delete))
        .nest_service("/static", ServeDir::new("static"))
        .with_state(state);

    let port = std::env::var("PORT").unwrap_or_else(|_| "8000".to_string());
    let addr = format!("0.0.0.0:{port}");
    tracing::info!("listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
