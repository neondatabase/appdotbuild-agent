use crate::processor::agent::{Agent, AgentState, Command, Event};
use dabgent_mq::{Envelope, EventHandler, EventStore, Handler};
use rig::completion::ToolDefinition;
use rig::message::{ToolResult, ToolResultContent};
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use std::pin::Pin;

type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

type ToolResultDyn = eyre::Result<Result<JsonValue, JsonValue>>;

pub trait Tool: Send + Sync {
    type Args: for<'a> Deserialize<'a> + Serialize + Send + Sync;
    type Output: Serialize + Send + Sync;
    type Error: Serialize + Send + Sync;
    type Context: Send + Sync;

    fn name(&self) -> String;
    fn definition(&self) -> ToolDefinition;
    fn call(
        &self,
        ctx: &mut Self::Context,
        args: &Self::Args,
    ) -> impl Future<Output = Result<Self::Output, Self::Error>> + Send;
    fn parse_args(args: &JsonValue) -> eyre::Result<Self::Args> {
        serde_json::from_value(args.clone()).map_err(Into::into)
    }
    fn result_json(result: Result<Self::Output, Self::Error>) -> ToolResultDyn {
        Ok(match result {
            Ok(output) => Ok(serde_json::to_value(output)?),
            Err(error) => Err(serde_json::to_value(error)?),
        })
    }
}

pub trait ToolDyn<T>: Send + Sync {
    fn name(&self) -> String;
    fn definition(&self) -> ToolDefinition;
    fn call<'a>(&'a self, ctx: &'a mut T, args: &'a JsonValue) -> BoxFuture<'a, ToolResultDyn>;
}

impl<T: Tool> ToolDyn<T::Context> for T {
    fn name(&self) -> String {
        Tool::name(self)
    }

    fn definition(&self) -> ToolDefinition {
        self.definition()
    }

    fn call<'a>(
        &'a self,
        ctx: &'a mut T::Context,
        args: &'a JsonValue,
    ) -> BoxFuture<'a, ToolResultDyn> {
        Box::pin(async {
            let args = <T as Tool>::parse_args(args)?;
            <T as Tool>::result_json(self.call(ctx, &args).await)
        })
    }
}

pub trait CtxProvider: Send + Sync {
    type Context: Send + Sync;

    fn get_context(
        &self,
        aggregate_id: &str,
    ) -> impl Future<Output = eyre::Result<Self::Context>> + Send;

    fn put_context(
        &self,
        aggregate_id: &str,
        context: Self::Context,
    ) -> impl Future<Output = eyre::Result<()>> + Send;
}

pub struct ToolHandler<T: CtxProvider> {
    provider: T,
    tools: Vec<Box<dyn ToolDyn<T::Context>>>,
}

impl<T: CtxProvider> ToolHandler<T> {
    pub fn new(provider: T, tools: Vec<Box<dyn ToolDyn<T::Context>>>) -> Self {
        Self { provider, tools }
    }
}

impl<A, ES, P> EventHandler<AgentState<A>, ES> for ToolHandler<P>
where
    A: Agent,
    ES: EventStore,
    P: CtxProvider,
{
    async fn process(
        &mut self,
        handler: &Handler<AgentState<A>, ES>,
        event: &Envelope<AgentState<A>>,
    ) -> eyre::Result<()> {
        if let Event::ToolCalls { calls } = &event.data {
            let mut ctx = self.provider.get_context(&event.aggregate_id).await?;
            let mut results = Vec::new();
            for call in calls.iter() {
                let name = call.function.name.clone();
                let tool = match self.tools.iter().find(|t| t.name() == name) {
                    Some(tool) => tool,
                    None => continue,
                };
                let result = tool.call(&mut ctx, &call.function.arguments).await?;
                results.push(call.to_result(result));
            }
            if results.is_empty() {
                return Ok(());
            }
            let command = Command::PutToolResults { results };
            handler
                .execute_with_metadata(&event.aggregate_id, command, event.metadata.clone())
                .await?;
            self.provider.put_context(&event.aggregate_id, ctx).await?;
        }
        Ok(())
    }
}

pub trait ToolCallExt {
    fn to_result(&self, result: Result<serde_json::Value, serde_json::Value>) -> ToolResult;
}

impl ToolCallExt for rig::message::ToolCall {
    fn to_result(&self, result: Result<serde_json::Value, serde_json::Value>) -> ToolResult {
        let inner = match result {
            Ok(value) => value,
            Err(error) => serde_json::json!({"error": error}),
        };
        let inner = serde_json::to_string(&inner).unwrap();
        ToolResult {
            id: self.id.clone(),
            call_id: self.call_id.clone(),
            content: rig::OneOrMany::one(ToolResultContent::Text(inner.into())),
        }
    }
}
