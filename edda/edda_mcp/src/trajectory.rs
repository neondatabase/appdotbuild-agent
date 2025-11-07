use chrono::Utc;
use eyre::Result;
use rmcp::model::{CallToolRequestParam, CallToolResult, ServerInfo};
use rmcp::service::{RequestContext, RoleServer};
use rmcp::{ErrorData, ServerHandler};
use serde::{Deserialize, Serialize};
use std::io::Write as IoWrite;
use std::path::PathBuf;
use std::sync::Mutex;

use crate::paths;
use crate::providers::CombinedProvider;

#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "entry_type")]
pub enum HistoryEntry {
    #[serde(rename = "session")]
    Session(SessionMetadata),
    #[serde(rename = "tool")]
    Tool(TrajectoryEntry),
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SessionMetadata {
    pub session_id: String,
    pub timestamp: String,
    pub config: crate::config::Config,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct TrajectoryEntry {
    pub session_id: String,
    pub timestamp: String,
    pub tool_name: String,
    pub arguments: Option<serde_json::Value>,
    pub success: bool,
    pub result: Option<serde_json::Value>,
    pub error: Option<String>,
}

pub struct TrajectoryTrackingProvider {
    inner: CombinedProvider,
    history_file: Mutex<std::fs::File>,
    session_id: String,
}

impl TrajectoryTrackingProvider {
    pub fn new(inner: CombinedProvider, session_id: String, config: crate::config::Config) -> Result<Self> {
        let history_path = paths::trajectory_path()?;
        Self::new_with_path(inner, session_id, config, history_path)
    }

    #[doc(hidden)]
    pub fn new_with_path(
        inner: CombinedProvider,
        session_id: String,
        config: crate::config::Config,
        history_path: PathBuf,
    ) -> Result<Self> {
        // ensure parent directory exists
        if let Some(parent) = history_path.parent() {
            std::fs::create_dir_all(parent)?;
        }

        let history_file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(history_path)?;

        let provider = Self {
            inner,
            history_file: Mutex::new(history_file),
            session_id: session_id.clone(),
        };

        // write session metadata as first entry
        let session_metadata = SessionMetadata {
            session_id,
            timestamp: Utc::now().to_rfc3339(),
            config,
        };
        provider.record_history_entry(HistoryEntry::Session(session_metadata))?;

        Ok(provider)
    }

    fn record_history_entry(&self, entry: HistoryEntry) -> Result<()> {
        let json_line = serde_json::to_string(&entry)?;
        let mut file = self.history_file.lock().unwrap();
        writeln!(file, "{}", json_line)?;
        file.flush()?;
        Ok(())
    }

    fn record_trajectory(&self, entry: TrajectoryEntry) -> Result<()> {
        self.record_history_entry(HistoryEntry::Tool(entry))
    }
}

impl ServerHandler for TrajectoryTrackingProvider {
    fn get_info(&self) -> ServerInfo {
        self.inner.get_info()
    }

    async fn list_tools(
        &self,
        request: Option<rmcp::model::PaginatedRequestParam>,
        context: RequestContext<RoleServer>,
    ) -> Result<rmcp::model::ListToolsResult, ErrorData> {
        self.inner.list_tools(request, context).await
    }

    async fn call_tool(
        &self,
        params: CallToolRequestParam,
        ctx: RequestContext<RoleServer>,
    ) -> Result<CallToolResult, ErrorData> {
        let timestamp = Utc::now().to_rfc3339();
        let tool_name = params.name.to_string();
        let arguments = params.arguments.as_ref().map(|args| {
            serde_json::to_value(args).unwrap_or(serde_json::Value::Null)
        });

        // call inner provider
        let result = self.inner.call_tool(params, ctx).await;

        // record trajectory
        let entry = match &result {
            Ok(call_result) => TrajectoryEntry {
                session_id: self.session_id.clone(),
                timestamp,
                tool_name,
                arguments,
                success: !call_result.is_error.unwrap_or(false),
                result: Some(serde_json::to_value(call_result).unwrap_or(serde_json::Value::Null)),
                error: None,
            },
            Err(error_data) => TrajectoryEntry {
                session_id: self.session_id.clone(),
                timestamp,
                tool_name,
                arguments,
                success: false,
                result: None,
                error: Some(error_data.to_string()),
            },
        };

        if let Err(e) = self.record_trajectory(entry) {
            tracing::warn!("Failed to record trajectory: {}", e);
        }

        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{Config, IoConfig, TemplateConfig};
    use crate::providers::ProviderType;

    #[test]
    fn test_trajectory_entry_serialization_success() {
        let entry = TrajectoryEntry {
            session_id: "test-sess".to_string(),
            timestamp: "2025-10-29T10:00:00Z".to_string(),
            tool_name: "test_tool".to_string(),
            arguments: Some(serde_json::json!({"key": "value"})),
            success: true,
            result: Some(serde_json::json!({"output": "success"})),
            error: None,
        };

        let json_line = serde_json::to_string(&HistoryEntry::Tool(entry)).unwrap();
        let deserialized: HistoryEntry = serde_json::from_str(&json_line).unwrap();

        match deserialized {
            HistoryEntry::Tool(te) => {
                assert_eq!(te.session_id, "test-sess");
                assert_eq!(te.tool_name, "test_tool");
                assert!(te.success);
                assert!(te.error.is_none());
            }
            _ => panic!("Expected Tool entry"),
        }
    }

    #[test]
    fn test_trajectory_entry_serialization_error() {
        let entry = TrajectoryEntry {
            session_id: "test-sess".to_string(),
            timestamp: "2025-10-29T10:00:00Z".to_string(),
            tool_name: "failing_tool".to_string(),
            arguments: None,
            success: false,
            result: None,
            error: Some("Tool execution failed".to_string()),
        };

        let json_line = serde_json::to_string(&HistoryEntry::Tool(entry)).unwrap();
        let deserialized: HistoryEntry = serde_json::from_str(&json_line).unwrap();

        match deserialized {
            HistoryEntry::Tool(te) => {
                assert_eq!(te.session_id, "test-sess");
                assert!(!te.success);
                assert!(te.result.is_none());
                assert_eq!(te.error.unwrap(), "Tool execution failed");
            }
            _ => panic!("Expected Tool entry"),
        }
    }

    #[test]
    fn test_trajectory_entry_jsonl_format() {
        let entry = TrajectoryEntry {
            session_id: "abc123".to_string(),
            timestamp: "2025-10-29T12:34:56Z".to_string(),
            tool_name: "deploy_app".to_string(),
            arguments: Some(serde_json::json!({"name": "myapp"})),
            success: true,
            result: Some(serde_json::json!({"url": "https://example.com"})),
            error: None,
        };

        let json_line = serde_json::to_string(&HistoryEntry::Tool(entry)).unwrap();

        // should not contain newlines (JSONL requirement)
        assert!(!json_line.contains('\n'));

        // should be valid JSON
        let parsed: serde_json::Value = serde_json::from_str(&json_line).unwrap();
        assert!(parsed.is_object());

        // should have entry_type field
        let obj = parsed.as_object().unwrap();
        assert!(obj.contains_key("entry_type"));
        assert_eq!(obj["entry_type"], "tool");
    }

    #[test]
    fn test_session_metadata_serialization() {
        let config = Config {
            with_deployment: true,
            with_workspace_tools: false,
            required_providers: vec![ProviderType::Databricks, ProviderType::Io],
            io_config: Some(IoConfig {
                template: TemplateConfig::Trpc,
                validation: None,
                screenshot: None,
            }),
        };

        let metadata = SessionMetadata {
            session_id: "sess-123".to_string(),
            timestamp: "2025-10-29T10:00:00Z".to_string(),
            config,
        };

        let json_line = serde_json::to_string(&HistoryEntry::Session(metadata)).unwrap();

        // should not contain newlines
        assert!(!json_line.contains('\n'));

        // should deserialize correctly
        let deserialized: HistoryEntry = serde_json::from_str(&json_line).unwrap();
        match deserialized {
            HistoryEntry::Session(sm) => {
                assert_eq!(sm.session_id, "sess-123");
                assert!(sm.config.with_deployment);
                assert!(sm.config.io_config.is_some());
            }
            _ => panic!("Expected Session entry"),
        }
    }

    #[test]
    fn test_session_metadata_with_custom_template() {
        let config = Config {
            with_deployment: false,
            with_workspace_tools: true,
            required_providers: vec![ProviderType::Io],
            io_config: Some(IoConfig {
                template: TemplateConfig::Custom {
                    name: "MyTemplate".to_string(),
                    path: "/path/to/template".to_string(),
                },
                validation: None,
                screenshot: None,
            }),
        };

        let metadata = SessionMetadata {
            session_id: "sess-456".to_string(),
            timestamp: "2025-10-29T10:00:00Z".to_string(),
            config,
        };

        let json_line = serde_json::to_string(&HistoryEntry::Session(metadata)).unwrap();
        let deserialized: HistoryEntry = serde_json::from_str(&json_line).unwrap();

        match deserialized {
            HistoryEntry::Session(sm) => {
                assert_eq!(sm.session_id, "sess-456");
                assert!(!sm.config.with_deployment);
                assert!(sm.config.with_workspace_tools);
                match &sm.config.io_config.unwrap().template {
                    TemplateConfig::Custom { name, path } => {
                        assert_eq!(name, "MyTemplate");
                        assert_eq!(path, "/path/to/template");
                    }
                    _ => panic!("Expected Custom template"),
                }
            }
            _ => panic!("Expected Session entry"),
        }
    }
}
