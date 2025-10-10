use clap::Parser;
use std::env;

#[derive(Debug, Clone, Parser)]
#[command(name = "axum-app")]
#[command(about = "A modern Rust web application built with Axum")]
pub struct Config {
    /// Database URL for PostgreSQL connection
    #[arg(env = "DATABASE_URL")]
    pub database_url: String,

    /// Host to bind the server to
    #[arg(long, env = "HOST", default_value = "0.0.0.0")]
    pub host: String,

    /// Port to bind the server to
    #[arg(long, env = "PORT", default_value = "3000")]
    pub port: u16,

    /// JWT secret for authentication
    #[arg(env = "JWT_SECRET")]
    pub jwt_secret: Option<String>,

    /// Environment (development, production)
    #[arg(long, env = "RUST_ENV", default_value = "development")]
    pub environment: String,

    /// Log level
    #[arg(long, env = "RUST_LOG", default_value = "info")]
    pub log_level: String,
}

impl Config {
    pub fn from_env() -> Result<Self, crate::error::AppError> {
        // Ensure required environment variables are set
        if env::var("DATABASE_URL").is_err() {
            return Err(crate::error::AppError::ConfigError(
                "DATABASE_URL environment variable is required".to_string(),
            ));
        }

        let config = Self::parse();
        Ok(config)
    }

    pub fn is_production(&self) -> bool {
        self.environment == "production"
    }

    pub fn is_development(&self) -> bool {
        self.environment == "development"
    }

    #[cfg(test)]
    pub fn test() -> Self {
        Self {
            database_url: "postgresql://test:test@localhost/test_db".to_string(),
            host: "127.0.0.1".to_string(),
            port: 0, // Let the OS choose a free port
            jwt_secret: Some("test_secret_key_for_testing_only".to_string()),
            environment: "test".to_string(),
            log_level: "debug".to_string(),
        }
    }
}