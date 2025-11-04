use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::RwLock;

/// Session-scoped context shared across all providers in an MCP session.
///
/// Each MCP stdio connection creates a new session with isolated state.
/// This struct holds session-level data that providers may need to access.
#[derive(Debug, Clone)]
pub struct SessionContext {
    /// Optional session identifier (Some for binary mode, None for cargo run).
    /// Used for trajectory logging and debugging.
    pub session_id: Option<String>,

    /// Workspace directory path, set after successful scaffolding.
    /// Starts as None, gets set by scaffold_data_app tool.
    /// Used by WorkspaceTools to scope file operations to the project directory.
    pub work_dir: Arc<RwLock<Option<PathBuf>>>,

    /// Tracks whether any tool has been called in this session.
    /// Used to inject engine guidance on first tool call only.
    pub first_tool_called: Arc<RwLock<bool>>,
}

impl SessionContext {
    /// Create a new session context with optional session ID.
    /// Work directory starts unset and gets populated during scaffolding.
    pub fn new(session_id: Option<String>) -> Self {
        Self {
            session_id,
            work_dir: Arc::new(RwLock::new(None)),
            first_tool_called: Arc::new(RwLock::new(false)),
        }
    }
}
