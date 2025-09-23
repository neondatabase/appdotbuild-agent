use crate::event::Event;
use crate::llm::{CompletionResponse, FinishReason};
use crate::sandbox_seed::{collect_template_files, write_template_files};
use crate::toolbox::ToolDyn;
use dabgent_sandbox::SandboxDyn;
use eyre::Result;
use std::path::Path;

/// SandboxReplayer centralizes replay-only side effects for rebuilding the sandbox:
/// - Seeding from a host template (SandboxSeeded events)
/// - Re-invoking tool calls from agent messages (AgentMessage with ToolUse)
///
/// This keeps FinishProcessor lean and avoids duplicating logic that also lives in ToolProcessor.
/// It does not emit new events; it only applies side-effects to the sandbox for deterministic replay.
pub struct SandboxReplayer<'a> {
    pub sandbox: &'a mut Box<dyn SandboxDyn>,
    pub tools: &'a [Box<dyn ToolDyn>],
}

impl<'a> SandboxReplayer<'a> {
    pub fn new(sandbox: &'a mut Box<dyn SandboxDyn>, tools: &'a [Box<dyn ToolDyn>]) -> Self {
        Self { sandbox, tools }
    }

    /// Apply replay side-effects for a single event.
    pub async fn apply(&mut self, event: &Event) -> Result<()> {
        match event {
            Event::SandboxSeeded { template_path, base_path, .. } => {
                self.replay_template_seed(template_path, base_path).await?;
            }
            Event::AgentMessage { response, .. } if response.finish_reason == FinishReason::ToolUse => {
                self.replay_tool_calls(response).await?;
            }
            _ => {
                // No side-effects required for other events during replay
            }
        }
        Ok(())
    }

    /// Apply replay side-effects for a sequence of events.
    pub async fn apply_all(&mut self, events: &[Event]) -> Result<()> {
        for e in events {
            self.apply(e).await?;
        }
        Ok(())
    }

    async fn replay_template_seed(&mut self, template_path: &str, base_path: &str) -> Result<()> {
        match collect_template_files( Path::new(template_path), base_path) {
            Ok(tf) => {
                let count = write_template_files(self.sandbox, &tf.files).await?;
                tracing::debug!("Seeded {} files from template during replay", count);
            }
            Err(err) => {
                tracing::warn!("Failed to collect template files during replay: {:?}", err);
            }
        }
        Ok(())
    }

    async fn replay_tool_calls(&mut self, response: &CompletionResponse) -> Result<()> {
        tracing::debug!("Replaying tool calls from agent message during replay");
        for content in response.choice.iter() {
            if let rig::message::AssistantContent::ToolCall(call) = content {
                let tool_name = &call.function.name;
                let args = call.function.arguments.clone();

                match self.tools.iter().find(|t| t.name() == *tool_name) {
                    Some(tool) => {
                        if !tool.needs_replay() {
                            tracing::debug!("Skipping replay for non-replayable tool: {}", tool_name);
                        } else {
                            match tool.call(args, self.sandbox).await {
                                Ok(_) => tracing::debug!("Replayed tool call: {}", tool_name),
                                Err(e) => {
                                    tracing::warn!("Failed tool call during replay {}: {:?}", tool_name, e);
                                    return Err(eyre::eyre!("Tool call failed during replay: {}: {:?}", tool_name, e));
                                }
                            }
                        }
                    }
                    None => {
                        tracing::warn!("Tool not found during replay: {}", tool_name);
                    }
                }
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::Event;
    use crate::llm::{CompletionResponse, FinishReason};
    use crate::toolbox::Tool;
    use dabgent_sandbox::{ExecResult, Sandbox, SandboxDyn};
    use eyre::Result;
    use std::collections::HashMap;
    use std::sync::{Arc, atomic::{AtomicUsize, Ordering}};
    use tempfile::tempdir;

    #[derive(Default)]
    struct MockSandbox {
        files: HashMap<String, String>,
        execs: Vec<String>,
    }

    impl Sandbox for MockSandbox {
        async fn exec(&mut self, command: &str) -> eyre::Result<ExecResult> {
            self.execs.push(command.to_string());
            Ok(ExecResult { exit_code: 0, stdout: String::new(), stderr: String::new() })
        }

        async fn write_file(&mut self, path: &str, content: &str) -> eyre::Result<()> {
            self.files.insert(path.to_string(), content.to_string());
            Ok(())
        }

        async fn write_files(&mut self, files: Vec<(&str, &str)>) -> eyre::Result<()> {
            for (p, c) in files {
                self.files.insert(p.to_string(), c.to_string());
            }
            Ok(())
        }

        async fn read_file(&self, path: &str) -> eyre::Result<String> {
            self.files.get(path).cloned().ok_or_else(|| eyre::eyre!("not found"))
        }

        async fn delete_file(&mut self, path: &str) -> eyre::Result<()> {
            self.files.remove(path);
            Ok(())
        }

        async fn list_directory(&self, _path: &str) -> eyre::Result<Vec<String>> {
            Ok(self.files.keys().cloned().collect())
        }

        async fn set_workdir(&mut self, _path: &str) -> eyre::Result<()> {
            Ok(())
        }

        async fn export_directory(&self, _container_path: &str, _host_path: &str) -> eyre::Result<String> {
            Ok(String::new())
        }
    }

    #[derive(Clone, Default)]
    struct CountingTool {
        name: String,
        calls: Arc<AtomicUsize>,
        replay: bool,
    }

    impl CountingTool {
        fn new(name: &str, replay: bool) -> Self {
            Self { name: name.to_string(), calls: Arc::new(AtomicUsize::new(0)), replay }
        }
        fn count(&self) -> usize {
            self.calls.load(Ordering::SeqCst)
        }
    }

    #[derive(serde::Deserialize, serde::Serialize)]
    struct AnyArgs(serde_json::Value);

    impl Tool for CountingTool {
        type Args = AnyArgs;
        type Output = ();
        type Error = String;

        fn name(&self) -> String { self.name.clone() }
        fn definition(&self) -> rig::completion::ToolDefinition {
            rig::completion::ToolDefinition { name: Tool::name(self), description: "".into(), parameters: serde_json::json!({}) }
        }
        fn needs_replay(&self) -> bool { self.replay }
        async fn call(&self, _args: Self::Args, _sandbox: &mut Box<dyn SandboxDyn>) -> Result<Result<Self::Output, Self::Error>> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(Ok(()))
        }
    }

    fn make_tool_call(name: &str, args: serde_json::Value) -> rig::message::AssistantContent {
        use rig::message::{AssistantContent, ToolCall, ToolFunction};
        let function = ToolFunction { name: name.to_string(), arguments: args };
        let call = ToolCall { id: "id1".to_string(), call_id: Some("cid1".to_string()), function };
        AssistantContent::ToolCall(call)
    }

    #[tokio::test]
    async fn seeds_template_on_sandboxseeded_event() {
        // Arrange
        let dir = tempdir().unwrap();
        let tpath = dir.path();
        std::fs::create_dir_all(tpath.join("sub")).unwrap();
        std::fs::write(tpath.join("root.txt"), "root").unwrap();
        std::fs::write(tpath.join("sub/file.txt"), "hello").unwrap();

        let mut sandbox: Box<dyn SandboxDyn> = Box::new(MockSandbox::default());
        let tools: Vec<Box<dyn ToolDyn>> = vec![];

        let mut replayer = SandboxReplayer::new(&mut sandbox, &tools);

        // Act
        let evt = Event::SandboxSeeded {
            template_path: tpath.to_string_lossy().to_string(),
            base_path: "/app".to_string(),
            file_count: 2,
            template_hash: None,
        };
        replayer.apply(&evt).await.unwrap();

        // Assert
        // Files should be written into sandbox with base path
        let s = sandbox.read_file("/app/root.txt").await.unwrap();
        assert_eq!(s, "root");
        let s2 = sandbox.read_file("/app/sub/file.txt").await.unwrap();
        assert_eq!(s2, "hello");
    }

    #[tokio::test]
    async fn skips_non_replay_tools_and_runs_replayable_ones() {
        // Arrange
        let mut sandbox: Box<dyn SandboxDyn> = Box::new(MockSandbox::default());
        let read_tool = CountingTool::new("read_file", false);
        let write_tool = CountingTool::new("write_file", true);
        let tools: Vec<Box<dyn ToolDyn>> = vec![Box::new(read_tool.clone()), Box::new(write_tool.clone())];

        let mut replayer = SandboxReplayer::new(&mut sandbox, &tools);

        let tool_call_read = make_tool_call("read_file", serde_json::json!({"path": "x"}));
        let tool_call_write = make_tool_call("write_file", serde_json::json!({"path": "y", "contents": "z"}));
        let choice = rig::OneOrMany::many(vec![tool_call_read, tool_call_write]).unwrap();
        let resp = CompletionResponse { choice, finish_reason: FinishReason::ToolUse, output_tokens: 0 };

        // Act
        replayer.replay_tool_calls(&resp).await.unwrap();

        // Assert
        assert_eq!(read_tool.count(), 0, "read_file should not be replayed");
        assert_eq!(write_tool.count(), 1, "write_file should be replayed exactly once");
    }
}
