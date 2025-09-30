use super::{Aggregate, Processor};
use crate::event::{Event, TypedToolResult, ToolKind};
use crate::processor::thread;
use crate::toolbox::{Tool, ToolDyn, ToolCallExt};
use crate::llm::CompletionResponse;
use dabgent_mq::{EventDb, EventStore, Query};
use dabgent_sandbox::SandboxDyn;
use async_trait::async_trait;
use eyre::Result;
use serde::{Deserialize, Serialize};
use serde_json::json;

pub mod databricks;
pub mod compaction;

#[derive(Debug, Clone)]
pub enum DelegationContext {
    Databricks { catalog: String },
    Compaction { threshold: usize },
}

#[derive(Debug)]
pub struct DelegationResult {
    pub task_thread_id: String,
    pub config_event: Event,
    pub user_event: Event,
}

#[async_trait]
pub trait DelegationHandler: Send + Sync {
    fn trigger_tool(&self) -> &str;
    fn thread_prefix(&self) -> &str;
    fn worker_name(&self) -> &str;

    // Handler owns its sandbox and tools
    fn tools(&self) -> &[Box<dyn ToolDyn>];
    fn sandbox_mut(&mut self) -> &mut Box<dyn SandboxDyn>;

    // Execute a tool by name - this avoids borrowing conflicts
    async fn execute_tool_by_name(
        &mut self,
        tool_name: &str,
        args: serde_json::Value
    ) -> eyre::Result<Result<serde_json::Value, serde_json::Value>>;

    // Check if this handler should process a specific event
    fn should_handle_tools(&self, event: &EventDb<Event>) -> bool {
        if let Event::AgentMessage { recipient: Some(r), .. } = &event.data {
            r == self.worker_name() && event.aggregate_id.starts_with(self.thread_prefix())
        } else {
            false
        }
    }

    // Create context from tool call arguments
    fn create_context(&self, tool_call: &rig::message::ToolCall) -> Result<DelegationContext>;

    // Create completion result for returning to parent thread
    fn create_completion_result(&self, summary: &str, parent_tool_id: &str) -> TypedToolResult;

    // Determine if this handler should handle a specific tool result
    fn should_handle(&self, result: &TypedToolResult) -> bool;

    // Extract prompt argument from tool call or tool result (handler-specific logic)
    fn extract_prompt(&self, tool_call: &rig::message::ToolCall, _tool_result: &TypedToolResult) -> String {
        // Default: extract from tool call arguments
        tool_call.function.arguments.get("prompt")
            .and_then(|v| v.as_str())
            .unwrap_or("Explore the catalog for relevant data")
            .to_string()
    }

    fn handle(
        &self,
        context: DelegationContext,
        prompt: &str,
        model: &str,
        parent_aggregate_id: &str,
        parent_tool_id: &str
    ) -> Result<DelegationResult>;
    fn format_result(&self, summary: &str) -> String;
}

pub struct DelegationProcessor<E: EventStore> {
    event_store: E,
    default_model: String,
    handlers: Vec<Box<dyn DelegationHandler>>,
}

impl<E: EventStore> Processor<Event> for DelegationProcessor<E> {
    async fn run(&mut self, event: &EventDb<Event>) -> eyre::Result<()> {
        match &event.data {
            Event::AgentMessage { response, .. } if self.has_delegation_trigger_tool_call(response) => {
                tracing::info!(
                    "Delegation trigger tool call detected for aggregate {}",
                    event.aggregate_id
                );
                self.handle_delegation_trigger(event, response).await?;
            }
            Event::ToolResult(tool_results) if self.is_delegation_tool_result(tool_results) => {
                tracing::info!(
                    "Delegation tool result detected for aggregate {}",
                    event.aggregate_id
                );
                self.handle_delegation_request(event, tool_results).await?;
            }
            Event::AgentMessage { response, .. } if self.is_delegated_tool_execution(event) => {
                tracing::info!(
                    "Tool execution detected for delegated thread {}",
                    event.aggregate_id
                );
                self.handle_tool_execution(event, response).await?;
            }
            Event::ToolResult(tool_results) if !self.is_delegation_tool_result(tool_results) => {
                // Skip non-delegation tool results - they're handled by their respective ToolProcessors
            }
            Event::WorkComplete { result, .. } if self.is_delegated_thread(&event.aggregate_id) => {
                tracing::info!(
                    "Delegated work completed successfully for aggregate {}",
                    event.aggregate_id,
                );
                self.handle_work_completion(event, result).await?;
            }
            Event::DelegateWork { agent_type, prompt, parent_tool_id } => {
                tracing::info!(
                    "Delegation work request detected for agent_type {} in aggregate {}",
                    agent_type, event.aggregate_id
                );
                self.handle_delegate_work(event, agent_type, prompt, parent_tool_id).await?;
            }
            _ => {}
        }
        Ok(())
    }
}

impl<E: EventStore> DelegationProcessor<E> {
    pub fn new(event_store: E, default_model: String, handlers: Vec<Box<dyn DelegationHandler>>) -> Self {
        Self {
            event_store,
            default_model,
            handlers,
        }
    }

    fn has_delegation_trigger_tool_call(&self, response: &CompletionResponse) -> bool {
        response.choice.iter().any(|content| {
            if let rig::message::AssistantContent::ToolCall(call) = content {
                self.handlers.iter().any(|h| h.trigger_tool() == call.function.name)
            } else {
                false
            }
        })
    }

    async fn handle_delegation_trigger(&mut self, event: &EventDb<Event>, response: &CompletionResponse) -> eyre::Result<()> {
        // Extract trigger tool calls and start delegation for each
        for content in response.choice.iter() {
            if let rig::message::AssistantContent::ToolCall(call) = content {
                if let Some(handler_idx) = self.handlers.iter().position(|h| h.trigger_tool() == call.function.name) {
                    let prompt = call.function.arguments
                        .get("prompt")
                        .and_then(|v| v.as_str())
                        .unwrap_or("");

                    // Create context using handler's own logic
                    let context = self.handlers[handler_idx].create_context(call)?;

                    // Create delegation using handler
                    let result = self.handlers[handler_idx]
                        .handle(context, prompt, &self.default_model, &event.aggregate_id, &call.id)?;

                    // Push events to start delegation
                    self.event_store.push_event(
                        &event.stream_id,
                        &result.task_thread_id,
                        &result.config_event,
                        &Default::default()
                    ).await?;

                    self.event_store.push_event(
                        &event.stream_id,
                        &result.task_thread_id,
                        &result.user_event,
                        &Default::default()
                    ).await?;
                }
            }
        }
        Ok(())
    }

    fn is_delegated_thread(&self, aggregate_id: &str) -> bool {
        self.handlers.iter().any(|h| aggregate_id.starts_with(h.thread_prefix()))
    }

    fn is_delegation_tool_result(&self, tool_results: &[crate::event::TypedToolResult]) -> bool {
        // Check if any handler should handle any of the tool results
        tool_results.iter().any(|result| {
            self.handlers.iter().any(|handler| handler.should_handle(result))
        })
    }



    async fn handle_delegation_request(
        &mut self,
        event: &EventDb<Event>,
        tool_results: &[crate::event::TypedToolResult],
    ) -> eyre::Result<()> {
        // Find a tool result that a handler can handle
        for delegation_result in tool_results.iter() {
            // Find matching handler using should_handle
            let handler_idx = self.handlers.iter()
                .position(|h| h.should_handle(delegation_result));

            if let Some(handler_idx) = handler_idx {
                let parent_tool_id = delegation_result.result.id.clone();
                // Load events to find the original tool call with arguments
                let query = Query::stream(&event.stream_id).aggregate(&event.aggregate_id);
                let events = self.event_store.load_events::<Event>(&query, None).await?;

                // Find the most recent AgentMessage with the matching tool call
                let tool_call = events.iter().rev()
                    .find_map(|e| match e {
                        Event::AgentMessage { response, .. } => {
                            response.choice.iter().find_map(|content| {
                                if let rig::message::AssistantContent::ToolCall(call) = content {
                                    if call.id == parent_tool_id {
                                        Some(call)
                                    } else {
                                        None
                                    }
                                } else {
                                    None
                                }
                            })
                        }
                        _ => None,
                    });

                if let Some(tool_call) = tool_call {
                    // Let handler extract prompt using its own logic (may extract from tool call args or tool result content)
                    let prompt_arg = self.handlers[handler_idx].extract_prompt(tool_call, delegation_result);

                    // Create context using handler's own logic
                    let context = self.handlers[handler_idx].create_context(tool_call)?;

                    self.handle_delegation_by_index(event, handler_idx, context, &prompt_arg, &parent_tool_id).await?;
                } else {
                    return Err(eyre::eyre!(
                        "Could not find original tool call with id '{}' for delegation",
                        parent_tool_id
                    ));
                }
            }
        }

        Ok(())
    }

    async fn handle_delegate_work(
        &mut self,
        event: &EventDb<Event>,
        agent_type: &str,
        prompt: &str,
        parent_tool_id: &str,
    ) -> eyre::Result<()> {
        // Find handler based on worker name (agent_type maps to worker_name)
        let handler_idx = self.handlers.iter()
            .position(|h| h.worker_name() == agent_type)
            .ok_or_else(|| eyre::eyre!("No handler found for agent_type '{}'", agent_type))?;

        // Create a dummy tool call to extract context from handler
        // For DelegateWork events triggered by ToolProcessor, we don't have a real tool call
        // So we create a minimal one with empty arguments - handlers should use defaults
        let dummy_call = rig::message::ToolCall {
            id: parent_tool_id.to_string(),
            call_id: None,
            function: rig::message::ToolFunction {
                name: self.handlers[handler_idx].trigger_tool().to_string(),
                arguments: serde_json::Value::Object(Default::default()),
            },
        };

        // Create context using handler's own logic
        let context = self.handlers[handler_idx].create_context(&dummy_call)?;

        // Delegate work to the appropriate handler
        self.handle_delegation_by_index(event, handler_idx, context, prompt, parent_tool_id).await
    }

    async fn handle_delegation_by_index(
        &mut self,
        event: &EventDb<Event>,
        handler_idx: usize,
        context: DelegationContext,
        prompt_arg: &str,
        parent_tool_id: &str,
    ) -> eyre::Result<()> {
        let result = self.handlers[handler_idx].handle(
            context,
            prompt_arg,
            &self.default_model,
            &event.aggregate_id,
            parent_tool_id,
        )?;

        // Send LLMConfig first with parent tracking
        self.event_store
            .push_event(
                &event.stream_id,
                &result.task_thread_id,
                &result.config_event,
                &Default::default(),
            )
            .await?;

        // Send the exploration task
        self.event_store
            .push_event(
                &event.stream_id,
                &result.task_thread_id,
                &result.user_event,
                &Default::default(),
            )
            .await?;

        Ok(())
    }

    async fn handle_work_completion(
        &mut self,
        event: &EventDb<Event>,
        summary: &str,
    ) -> eyre::Result<()> {
        // Load task thread to get parent info from LLMConfig
        let task_query = Query::stream(&event.stream_id).aggregate(&event.aggregate_id);
        let task_events = self.event_store.load_events::<Event>(&task_query, None).await?;

        // Find the LLMConfig event to get parent info
        let parent_info = task_events.iter()
            .find_map(|e| match e {
                Event::LLMConfig { parent, .. } => parent.as_ref(),
                _ => None,
            });

        if let Some(parent) = parent_info {
            // Find matching handler based on thread prefix
            let handler = self.handlers.iter()
                .find(|h| event.aggregate_id.starts_with(h.thread_prefix()));

            if let Some(handler) = handler {
                if let Some(tool_id) = &parent.tool_id {
                    // Use handler's create_completion_result to get the appropriate result type
                    let completion_result = vec![handler.create_completion_result(summary, tool_id)];

                    // Convert ToolResult to UserMessage for thread processing
                    let tools = completion_result.iter().map(|t| rig::message::UserContent::ToolResult(t.result.clone()));
                    let user_content = rig::OneOrMany::many(tools)?;

                    // Load original thread state and process
                    let original_query = Query::stream(&event.stream_id).aggregate(&parent.aggregate_id);
                    let events = self.event_store.load_events::<Event>(&original_query, None).await?;
                    let mut thread = thread::Thread::fold(&events);
                    let new_events = thread.process(thread::Command::User(user_content))?;

                    for new_event in new_events.iter() {
                        self.event_store
                            .push_event(
                                &event.stream_id,
                                &parent.aggregate_id,
                                new_event,
                                &Default::default(),
                            )
                            .await?;
                    }
                }
            }
        }

        Ok(())
    }

    fn is_delegated_tool_execution(&self, event: &EventDb<Event>) -> bool {
        self.handlers.iter().any(|h| h.should_handle_tools(event))
    }

    async fn handle_tool_execution(
        &mut self,
        event: &EventDb<Event>,
        response: &CompletionResponse
    ) -> eyre::Result<()> {
        // Find the handler for this event
        let handler_idx = self.handlers.iter()
            .position(|h| h.should_handle_tools(event))
            .ok_or_else(|| eyre::eyre!("No handler found for tool execution"))?;

        let mut tool_results = Vec::new();

        // Collect tool calls first to avoid borrowing issues
        let mut tool_calls = Vec::new();
        for content in response.choice.iter() {
            if let rig::message::AssistantContent::ToolCall(call) = content {
                tool_calls.push(call.clone());
            }
        }

        // Execute each tool call using the handler's execute_tool_by_name method
        for call in tool_calls {
            let tool_name = call.function.name.clone();
            let args = call.function.arguments.clone();

            // Execute using the handler's method which handles borrowing internally
            let result = self.handlers[handler_idx]
                .execute_tool_by_name(&tool_name, args)
                .await?;

            let tool_kind = match tool_name.as_str() {
                "finish_delegation" => ToolKind::FinishDelegation,
                other => ToolKind::Regular(other.to_string()),
            };

            let tool_result = call.to_result(result);
            tool_results.push(TypedToolResult {
                tool_name: tool_kind,
                result: tool_result,
            });
        }

        if !tool_results.is_empty() {
            // Push the ToolResult event first
            self.event_store.push_event(
                &event.stream_id,
                &event.aggregate_id,
                &Event::ToolResult(tool_results.clone()),
                &Default::default()
            ).await?;

            // Convert ToolResults to UserMessage only if they're not from terminal tools
            // Terminal tools complete the delegated work and don't need further LLM processing
            let non_terminal_results: Vec<_> = tool_results.iter()
                .filter(|tr| {
                    match &tr.tool_name {
                        ToolKind::Regular(tool_name) => {
                            // Check if this tool is terminal by finding it in handler tools
                            let is_terminal = self.handlers[handler_idx].tools()
                                .iter()
                                .find(|t| t.name() == *tool_name)
                                .map(|t| t.is_terminal())
                                .unwrap_or(false);
                            !is_terminal
                        }
                        ToolKind::FinishDelegation => false, // Terminal tool
                        _ => true, // Other ToolKind variants are not terminal
                    }
                })
                .collect();

            if !non_terminal_results.is_empty() {
                let tools = non_terminal_results.iter().map(|t|
                    rig::message::UserContent::ToolResult(t.result.clone())
                );
                let user_content = rig::OneOrMany::many(tools)?;

                // Load thread state and process the UserMessage
                let query = Query::stream(&event.stream_id).aggregate(&event.aggregate_id);
                let events = self.event_store.load_events::<Event>(&query, None).await?;
                let mut thread = thread::Thread::fold(&events);
                let new_events = thread.process(thread::Command::User(user_content))?;

                // Push the new events (including UserMessage and any LLM responses)
                for new_event in new_events.iter() {
                    self.event_store
                        .push_event(
                            &event.stream_id,
                            &event.aggregate_id,
                            new_event,
                            &Default::default(),
                        )
                        .await?;
                }
            }
        }

        Ok(())
    }
}

// Unified terminal tool for all delegation handlers
#[derive(Deserialize, Serialize)]
pub struct FinishDelegationArgs {
    pub result: String,
}

#[derive(Serialize)]
pub struct FinishDelegationOutput {
    pub success: String,
}

pub struct FinishDelegationTool;

impl Tool for FinishDelegationTool {
    type Args = FinishDelegationArgs;
    type Output = FinishDelegationOutput;
    type Error = serde_json::Value;

    fn name(&self) -> String {
        "finish_delegation".to_string()
    }

    fn definition(&self) -> rig::completion::ToolDefinition {
        rig::completion::ToolDefinition {
            name: Tool::name(self),
            description: "Complete the delegated work with a result summary".to_string(),
            parameters: json!({
                "type": "object",
                "properties": {
                    "result": {
                        "type": "string",
                        "description": "The result of the delegated work"
                    }
                },
                "required": ["result"]
            }),
        }
    }

    fn is_terminal(&self) -> bool {
        true
    }

    async fn call(
        &self,
        args: Self::Args,
        _sandbox: &mut Box<dyn SandboxDyn>,
    ) -> Result<Result<Self::Output, Self::Error>> {
        Ok(Ok(FinishDelegationOutput {
            success: format!("Delegated work completed: {}", args.result),
        }))
    }
}