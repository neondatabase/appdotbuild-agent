use super::{Aggregate, Processor, thread};
use crate::event::{Event, TypedToolResult, ToolKind};
use crate::llm::{CompletionResponse, FinishReason};
use crate::toolbox::{ToolCallExt, ToolDyn};
use dabgent_mq::{EventDb, EventStore, Query};
use dabgent_sandbox::SandboxDyn;
use eyre::Result;
use std::path::Path;
use crate::sandbox_seed::{collect_template_files, write_template_files};


pub struct ToolProcessor<E: EventStore> {
    sandbox: Box<dyn SandboxDyn>,
    event_store: E,
    tools: Vec<Box<dyn ToolDyn>>,
    recipient: Option<String>,
}

impl<E: EventStore> Processor<Event> for ToolProcessor<E> {
    async fn run(&mut self, event: &EventDb<Event>) -> eyre::Result<()> {
        match &event.data {
            Event::SeedSandboxFromTemplate { template_path, base_path } => {
                // Seed sandbox from template on host filesystem
                let template_path = Path::new(template_path);
                if !template_path.exists() {
                    tracing::warn!("Template path does not exist: {:?}", template_path);
                } else {
                    match collect_template_files(template_path, base_path) {
                        Err(err) => {
                            tracing::error!("Failed to collect template files: {:?}", err);
                        }
                        Ok(tf) => {
                            let template_hash = tf.hash.clone();
                            let template_path_str = template_path.display().to_string();

                            let file_count = tf.files.len();
                            if let Err(err) = write_template_files(&mut self.sandbox, &tf.files).await {
                                tracing::error!("Failed to write template files to sandbox: {:?}", err);
                            } else {
                                let seeded = Event::SandboxSeeded {
                                    template_path: template_path_str,
                                    base_path: base_path.clone(),
                                    file_count,
                                    template_hash: Some(template_hash),
                                };
                                self.event_store
                                    .push_event(&event.stream_id, &event.aggregate_id, &seeded, &Default::default())
                                    .await?;
                            }
                        }
                    }
                }
            }
            // Phase 1: AgentMessage with ToolUse -> emit ToolResult
            Event::AgentMessage {
                response,
                recipient,
                ..
            } if response.finish_reason == FinishReason::ToolUse
                && recipient.eq(&self.recipient) =>
            {
                let tool_results = self.run_tools(&response).await?;

                if !tool_results.is_empty() {
                    // Emit tool results as-is
                    let tool_result_event = Event::ToolResult(tool_results.clone());
                    self.event_store.push_event(
                        &event.stream_id,
                        &event.aggregate_id,
                        &tool_result_event,
                        &Default::default(),
                    ).await?;

                    // Convert to UserMessage for normal processing
                    let tools = tool_results.iter().map(|t|
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

            _ => {}
        }
        Ok(())
    }
}

impl<E: EventStore> ToolProcessor<E> {
    pub fn new(
        sandbox: Box<dyn SandboxDyn>,
        event_store: E,
        tools: Vec<Box<dyn ToolDyn>>,
        recipient: Option<String>,
    ) -> Self {
        Self {
            sandbox,
            event_store,
            tools,
            recipient,
        }
    }

    async fn run_tools(
        &mut self,
        response: &CompletionResponse,
    ) -> Result<Vec<TypedToolResult>> {
        let mut results = Vec::new();
        for content in response.choice.iter() {
            if let rig::message::AssistantContent::ToolCall(call) = content {
                let tool = self.tools.iter().find(|t| t.name() == call.function.name);
                let result = match tool {
                    Some(tool) => {
                        let args = call.function.arguments.clone();
                        let tool_result = tool.call(args, &mut self.sandbox).await?;

                        tool_result
                    }
                    None => {
                        let available_tools: Vec<String> = self.tools.iter()
                            .map(|tool| tool.name())
                            .collect();
                        let error = format!(
                            "Tool '{}' does not exist. Available tools: [{}]",
                            call.function.name,
                            available_tools.join(", ")
                        );
                        Err(serde_json::json!(error))
                    }
                };
                results.push(TypedToolResult {
                    tool_name: match call.function.name.as_str() {
                        "done" => ToolKind::Done,
                        "explore_databricks_catalog" => ToolKind::ExploreDatabricksCatalog,
                        "finish_delegation" => ToolKind::FinishDelegation,
                        "compact_error" => ToolKind::CompactError,
                        other => ToolKind::Regular(other.to_string())
                    },
                    result: call.to_result(result)
                });
            }
        }

        Ok(results)
    }
}
