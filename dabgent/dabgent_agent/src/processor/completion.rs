use super::Processor;
use crate::event::{Event, TypedToolResult, ToolKind};
use dabgent_mq::{EventDb, EventStore, Query};
use eyre::Result;

pub struct CompletionProcessor<E: EventStore> {
    event_store: E,
}

impl<E: EventStore> CompletionProcessor<E> {
    pub fn new(event_store: E) -> Self {
        Self { event_store }
    }

    async fn emit_task_completed(
        &mut self,
        event: &EventDb<Event>,
        result: &TypedToolResult,
    ) -> Result<()> {
        // extract summary from tool result content
        let summary = result.result.content.iter()
            .filter_map(|content| match content {
                rig::message::ToolResultContent::Text(text) => Some(text.text.clone()),
                _ => None,
            })
            .collect::<Vec<_>>()
            .join("\n");

        // check if Done tool succeeded by examining the tool result content structure
        let success = result.result.content.iter().all(|content| {
            match content {
                rig::message::ToolResultContent::Text(text) => {
                    // parse as JSON - if it has "error" field, Done failed
                    if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&text.text) {
                        if let Some(obj) = parsed.as_object() {
                            !obj.contains_key("error")
                        } else {
                            true
                        }
                    } else {
                        true
                    }
                }
                _ => true,
            }
        });

        if success {
            tracing::info!("Task completed successfully, emitting TaskCompleted event");
        } else {
            tracing::info!("Task completed with errors, emitting TaskCompleted event with success=false");
        }

        let task_completed_event = Event::TaskCompleted {
            success,
            summary: if summary.is_empty() { "Task completed".to_string() } else { summary }
        };

        self.event_store.push_event(
            &event.stream_id,
            &event.aggregate_id,
            &task_completed_event,
            &Default::default(),
        ).await?;

        Ok(())
    }

    async fn emit_work_complete(
        &mut self,
        event: &EventDb<Event>,
        result: &TypedToolResult,
    ) -> Result<()> {
        // load thread history to get parent info from LLMConfig
        let query = Query::stream(&event.stream_id).aggregate(&event.aggregate_id);
        let events = self.event_store.load_events::<Event>(&query, None).await?;

        // find LLMConfig with parent field
        let parent = events.iter()
            .find_map(|e| match e {
                Event::LLMConfig { parent: Some(p), .. } => Some(p.clone()),
                _ => None,
            })
            .ok_or_else(|| eyre::eyre!("Missing parent info in LLMConfig for finish_delegation"))?;

        // extract result from tool result content
        let summary = result.result.content.iter()
            .filter_map(|content| match content {
                rig::message::ToolResultContent::Text(text) => Some(text.text.clone()),
                _ => None,
            })
            .collect::<Vec<_>>()
            .join("\n");

        tracing::info!("Delegated work completed, emitting WorkComplete event");

        let work_complete_event = Event::WorkComplete {
            agent_type: "delegated_worker".to_string(),
            result: summary,
            parent,
        };

        self.event_store.push_event(
            &event.stream_id,
            &event.aggregate_id,
            &work_complete_event,
            &Default::default(),
        ).await?;

        Ok(())
    }
}

impl<E: EventStore> Processor<Event> for CompletionProcessor<E> {
    async fn run(&mut self, event: &EventDb<Event>) -> eyre::Result<()> {
        match &event.data {
            Event::ToolResult(results) => {
                for result in results {
                    match &result.tool_name {
                        ToolKind::Done => {
                            self.emit_task_completed(event, result).await?;
                        }
                        ToolKind::FinishDelegation => {
                            self.emit_work_complete(event, result).await?;
                        }
                        _ => {}
                    }
                }
            }
            _ => {}
        }
        Ok(())
    }
}