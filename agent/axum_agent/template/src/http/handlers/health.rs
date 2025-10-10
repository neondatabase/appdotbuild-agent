use axum::{extract::State, http::StatusCode, response::IntoResponse, Json};
use diesel::prelude::*;
use serde_json::json;

use crate::{error::AppError, AppState};

/// Health check endpoint that also verifies database connectivity
pub async fn api_health(State(state): State<AppState>) -> Result<impl IntoResponse, AppError> {
    // Check database connectivity
    let mut conn = state.db.get()?;
    
    // Simple query to verify database is accessible
    let result: Result<i32, diesel::result::Error> = diesel::select(diesel::dsl::sql::<diesel::sql_types::Integer>("1")).get_result(&mut conn);
    
    match result {
        Ok(_) => Ok((
            StatusCode::OK,
            Json(json!({
                "status": "healthy",
                "database": "connected",
                "timestamp": chrono::Utc::now().to_rfc3339()
            })),
        )),
        Err(_) => Ok((
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({
                "status": "unhealthy",
                "database": "disconnected",
                "timestamp": chrono::Utc::now().to_rfc3339()
            })),
        )),
    }
}