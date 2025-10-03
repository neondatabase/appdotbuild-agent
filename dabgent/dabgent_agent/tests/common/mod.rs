/// Common test utilities for e2e tests
///
/// This module contains only truly duplicated code that is identical across tests.

use dabgent_mq::db::sqlite::SqliteStore;
use dabgent_mq::listener::PollingQueue;
use dabgent_sandbox::{DaggerSandbox, Sandbox};
use dabgent_agent::toolbox;
use eyre::Result;

/// Standard Python validator using uv
///
/// This validator is used by all tests that execute Python scripts.
pub struct PythonValidator;

impl toolbox::Validator for PythonValidator {
    async fn run(&self, sandbox: &mut DaggerSandbox) -> Result<Result<(), String>> {
        sandbox.exec("uv run main.py").await.map(|result| {
            if result.exit_code == 0 {
                Ok(())
            } else {
                Err(format!(
                    "code: {}\nstdout: {}\nstderr: {}",
                    result.exit_code, result.stdout, result.stderr
                ))
            }
        })
    }
}

/// Create an in-memory SQLite event store for testing
///
/// All tests use the same store configuration.
pub async fn create_test_store() -> PollingQueue<SqliteStore> {
    let pool = sqlx::SqlitePool::connect(":memory:")
        .await
        .expect("Failed to create in-memory SQLite pool");
    let store = SqliteStore::new(pool, "agent");
    store.migrate().await;
    PollingQueue::new(store)
}
