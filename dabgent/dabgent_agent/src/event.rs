use crate::llm::CompletionResponse;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParentAggregate {
    pub aggregate_id: String,
    pub tool_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum ToolKind {
    Done,
    ExploreDatabricksCatalog,
    FinishDelegation,
    CompactError,
    Regular(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TypedToolResult {
    pub tool_name: ToolKind,
    pub result: rig::message::ToolResult,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Event {
    LLMConfig {
        model: String,
        temperature: f64,
        max_tokens: u64,
        preamble: Option<String>,
        tools: Option<Vec<rig::completion::ToolDefinition>>,
        recipient: Option<String>,
        parent: Option<ParentAggregate>,
    },
    AgentMessage {
        response: CompletionResponse,
        recipient: Option<String>,
    },
    UserMessage(rig::OneOrMany<rig::message::UserContent>),
    ToolResult(Vec<TypedToolResult>),
    ArtifactsCollected(HashMap<String, String>),
    TaskCompleted {
        success: bool,
        summary: String,
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
    PlanCreated {
        tasks: Vec<String>,
    },
    PlanUpdated {
        tasks: Vec<String>,
    },
    DelegateWork {
        agent_type: String,
        prompt: String,
        parent_tool_id: String,
    },
    WorkComplete {
        agent_type: String,
        result: String,
        parent: ParentAggregate,
    },
}

impl dabgent_mq::Event for Event {
    const EVENT_VERSION: &'static str = "1.0";

    fn event_type(&self) -> &'static str {
        match self {
            Event::LLMConfig { .. } => "llm_config",
            Event::AgentMessage { .. } => "agent_message",
            Event::UserMessage(..) => "user_message",
            Event::ToolResult(..) => "tool_result",
            Event::ArtifactsCollected(..) => "artifacts_collected",
            Event::TaskCompleted { .. } => "task_completed",
            Event::SeedSandboxFromTemplate { .. } => "seed_sandbox_from_template",
            Event::SandboxSeeded { .. } => "sandbox_seeded",
            Event::PipelineShutdown => "pipeline_shutdown",
            Event::PlanCreated { .. } => "plan_created",
            Event::PlanUpdated { .. } => "plan_updated",
            Event::DelegateWork { .. } => "delegate_work",
            Event::WorkComplete { .. } => "work_complete",
        }
    }
}
