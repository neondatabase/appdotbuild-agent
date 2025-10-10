use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum AppError {
    #[error("Database connection error: {0}")]
    DatabaseConnectionError(String),

    #[error("Database error: {0}")]
    DatabaseError(#[from] diesel::result::Error),

    #[error("Configuration error: {0}")]
    ConfigError(String),

    #[error("Migration error: {0}")]
    MigrationError(String),

    #[error("Server start error: {0}")]
    ServerStartError(String),

    #[error("Validation error: {0}")]
    ValidationError(String),

    #[error("Authentication failed")]
    AuthenticationFailed,

    #[error("Authorization failed")]
    AuthorizationFailed,

    #[error("Resource not found")]
    NotFound,

    #[error("Bad request: {0}")]
    BadRequest(String),

    #[error("Internal server error")]
    InternalServerError,
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, error_message) = match &self {
            AppError::DatabaseError(_) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "Database error occurred".to_string(),
            ),
            AppError::DatabaseConnectionError(_) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "Database connection failed".to_string(),
            ),
            AppError::ConfigError(msg) => (StatusCode::INTERNAL_SERVER_ERROR, msg.clone()),
            AppError::MigrationError(_) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "Database migration failed".to_string(),
            ),
            AppError::ServerStartError(_) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "Server failed to start".to_string(),
            ),
            AppError::ValidationError(msg) => (StatusCode::BAD_REQUEST, msg.clone()),
            AppError::AuthenticationFailed => (
                StatusCode::UNAUTHORIZED,
                "Authentication failed".to_string(),
            ),
            AppError::AuthorizationFailed => (
                StatusCode::FORBIDDEN,
                "Authorization failed".to_string(),
            ),
            AppError::NotFound => (StatusCode::NOT_FOUND, "Resource not found".to_string()),
            AppError::BadRequest(msg) => (StatusCode::BAD_REQUEST, msg.clone()),
            AppError::InternalServerError => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "Internal server error".to_string(),
            ),
        };

        // Log the actual error for debugging (but don't expose to client)
        tracing::error!("Application error: {}", self);

        let body = Json(json!({
            "error": error_message,
            "status": status.as_u16()
        }));

        (status, body).into_response()
    }
}

// Helper function to create validation errors
impl AppError {
    pub fn validation<T: ToString>(message: T) -> Self {
        Self::ValidationError(message.to_string())
    }

    pub fn bad_request<T: ToString>(message: T) -> Self {
        Self::BadRequest(message.to_string())
    }
}

// For compatibility with anyhow
impl From<anyhow::Error> for AppError {
    fn from(_err: anyhow::Error) -> Self {
        AppError::InternalServerError
    }
}

// For connection pool errors
impl From<diesel::r2d2::PoolError> for AppError {
    fn from(err: diesel::r2d2::PoolError) -> Self {
        AppError::DatabaseConnectionError(err.to_string())
    }
}