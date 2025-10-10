use axum::{routing::get, Router};

use crate::AppState;

pub fn api_routes() -> Router<AppState> {
    Router::new()
        .route("/api/health", get(super::handlers::health::api_health))
        // Add more API routes here as needed
        // .route("/api/users", get(handlers::users::list_users).post(handlers::users::create_user))
        // .route("/api/users/{id}", get(handlers::users::get_user).put(handlers::users::update_user).delete(handlers::users::delete_user))
}