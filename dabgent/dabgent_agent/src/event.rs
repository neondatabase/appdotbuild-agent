use crate::llm::CompletionResponse;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Event {
    LLMConfig {
        model: String,
        temperature: f64,
        max_tokens: u64,
        preamble: Option<String>,
        tools: Option<Vec<rig::completion::ToolDefinition>>,
        recipient: Option<String>,
    },
    AgentMessage {
        response: CompletionResponse,
        recipient: Option<String>,
    },
    UserMessage(rig::OneOrMany<rig::message::UserContent>),
    ArtifactsCollected(HashMap<String, String>),
    TaskCompleted {
        success: bool,
    },
    SeedSandboxFromTemplate {
        template_path: String,
        base_path: String,
    },
    SandboxSeeded {
        template_path: String,
        base_path: String,
        file_count: usize,
        template_hash: Option<String>,
    },
    PipelineShutdown,
}

impl dabgent_mq::Event for Event {
    const EVENT_VERSION: &'static str = "1.0";

    fn event_type(&self) -> &'static str {
        match self {
            Event::LLMConfig { .. } => "llm_config",
            Event::AgentMessage { .. } => "agent_message",
            Event::UserMessage(..) => "user_message",
            Event::ArtifactsCollected(..) => "artifacts_collected",
            Event::TaskCompleted { .. } => "task_completed",
            Event::SeedSandboxFromTemplate { .. } => "seed_sandbox_from_template",
            Event::SandboxSeeded { .. } => "sandbox_seeded",
            Event::PipelineShutdown => "pipeline_shutdown",
        }
    }
}
