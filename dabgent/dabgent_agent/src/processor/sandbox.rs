use super::{Aggregate, Processor};
use crate::event::Event;
use crate::llm::{CompletionResponse, FinishReason};
use crate::processor::thread::{self};
use crate::toolbox::{ToolCallExt, ToolDyn};
use dabgent_mq::{EventDb, EventStore, Query};
use dabgent_sandbox::SandboxDyn;
use eyre::Result;

pub struct ToolProcessor<E: EventStore> {
    sandbox: Box<dyn SandboxDyn>,
    event_store: E,
    tools: Vec<Box<dyn ToolDyn>>,
    recipient: Option<String>,
}

impl<E: EventStore> Processor<Event> for ToolProcessor<E> {
    async fn run(&mut self, event: &EventDb<Event>) -> eyre::Result<()> {
        let query = Query::stream(&event.stream_id).aggregate(&event.aggregate_id);
        match &event.data {
            Event::AgentMessage {
                response,
                recipient,
            } if response.finish_reason == FinishReason::ToolUse
                && recipient.eq(&self.recipient) =>
            {
                let events = self.event_store.load_events::<Event>(&query, None).await?;
                let mut thread = thread::Thread::fold(&events);
                let tools = self.run_tools(&response, &event.stream_id, &event.aggregate_id).await?;
                let tools = tools.into_iter().map(rig::message::UserContent::ToolResult);
                let content = rig::OneOrMany::many(tools)?;
                let new_events = thread.process(thread::Command::User(content))?;
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
        stream_id: &str,
        aggregate_id: &str,
    ) -> Result<Vec<rig::message::ToolResult>> {
        let mut results = Vec::new();

        for content in response.choice.iter() {
            if let rig::message::AssistantContent::ToolCall(call) = content {
                let tool = self.tools.iter().find(|t| t.name() == call.function.name);
                let result = match tool {
                    Some(tool) => {
                        let args = call.function.arguments.clone();
                        let tool_result = tool.call(args, &mut self.sandbox).await?;

                        // Check if this is a successful DoneTool call
                        match tool {
                            _ if call.function.name == "done" && tool_result.is_ok() => {
                                tracing::info!("Task completed successfully, emitting TaskCompleted event");
                                let task_completed_event = Event::TaskCompleted { success: true };
                                self.event_store
                                    .push_event(
                                        stream_id,
                                        aggregate_id,
                                        &task_completed_event,
                                        &Default::default(),
                                    )
                                    .await?;
                            }
                            _ => {}
                        }
                        tool_result
                    }
                    None => {
                        let error = format!("{} not found", call.function.name);
                        Err(serde_json::json!(error))
                    }
                };
                results.push(call.to_result(result));
            }
        }

        Ok(results)
    }
}
