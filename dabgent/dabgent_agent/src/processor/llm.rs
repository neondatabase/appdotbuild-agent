use super::agent::{Agent, AgentState, Command, Event};
use crate::llm::{Completion, CompletionResponse, LLMClientDyn};
use dabgent_mq::{Envelope, EventHandler, EventStore, Handler};
use eyre::{OptionExt, Result};
use rig::completion::ToolDefinition;
use std::sync::Arc;

pub struct LLMConfig {
    pub model: String,
    pub temperature: f64,
    pub max_tokens: u64,
    pub preamble: Option<String>,
    pub tools: Option<Vec<ToolDefinition>>,
}

impl Default for LLMConfig {
    fn default() -> Self {
        Self {
            model: "claude-sonnet-4-20250514".to_string(),
            temperature: 1.0,
            max_tokens: 8192,
            preamble: None,
            tools: None,
        }
    }
}

pub struct LLMHandler<A: Agent, ES: EventStore> {
    llm: Arc<dyn LLMClientDyn>,
    config: LLMConfig,
    _phantom: std::marker::PhantomData<(A, ES)>,
}

impl<A: Agent, ES: EventStore> LLMHandler<A, ES> {
    pub fn new(llm: Arc<dyn LLMClientDyn>, config: LLMConfig) -> Self {
        Self {
            llm,
            config,
            _phantom: std::marker::PhantomData,
        }
    }

    async fn handle_completion(
        &self,
        handler: &Handler<AgentState<A>, ES>,
        aggregate_id: &str,
    ) -> Result<CompletionResponse> {
        let ctx = handler
            .store()
            .load_aggregate::<AgentState<A>>(aggregate_id)
            .await?;
        let mut history = ctx.aggregate.messages.clone();
        let message = history.pop().ok_or_eyre("No messages")?;
        let mut completion = Completion::new(self.config.model.clone(), message)
            .history(history)
            .temperature(self.config.temperature)
            .max_tokens(self.config.max_tokens);
        if let Some(preamble) = &self.config.preamble {
            completion = completion.preamble(preamble.clone());
        }
        if let Some(ref tools) = self.config.tools {
            completion = completion.tools(tools.clone());
        }
        self.llm.completion(completion).await
    }
}

impl<A: Agent, ES: EventStore> EventHandler<AgentState<A>, ES> for LLMHandler<A, ES> {
    async fn process(
        &mut self,
        handler: &Handler<AgentState<A>, ES>,
        event: &Envelope<AgentState<A>>,
    ) -> Result<()> {
        if let Event::UserCompletion { .. } = &event.data {
            let response = self.handle_completion(handler, &event.aggregate_id).await?;
            handler
                .execute_with_metadata(
                    &event.aggregate_id,
                    Command::PutCompletion { response },
                    event.metadata.clone(),
                )
                .await?;
        }
        Ok(())
    }
}
