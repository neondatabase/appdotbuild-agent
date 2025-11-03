use crate::mcp_client::McpClient;
use anyhow::{Context, Result};
use rig::client::{CompletionClient, ProviderClient};
use rig::completion::{CompletionModel, CompletionRequest, ToolDefinition};
use rig::message::{AssistantContent, Message, ToolCall, ToolResult, ToolResultContent, UserContent};
use rig::providers::anthropic::Client as AnthropicClient;
use std::sync::Arc;
use tokio::sync::mpsc;
use tracing::{info, warn};

const MAX_TURNS: usize = 50;
const DEFAULT_MODEL: &str = "claude-sonnet-4-5-20250929";

const DEFAULT_SYSTEM_PROMPT: &str = "You are a helpful AI assistant with access to various tools. \
Use the available tools to help the user accomplish their tasks. \
Be concise and clear in your responses.";

#[derive(Clone)]
pub struct Agent {
    model: String,
    mcp_client: Arc<McpClient>,
    anthropic_client: Arc<AnthropicClient>,
    system_prompt: String,
    tools: Vec<ToolDefinition>,
}

impl Agent {
    pub fn new(mcp_client: Arc<McpClient>, tools: Vec<ToolDefinition>) -> Result<Self> {
        let anthropic_client = Arc::new(AnthropicClient::from_env());

        Ok(Self {
            model: DEFAULT_MODEL.to_string(),
            mcp_client,
            anthropic_client,
            system_prompt: DEFAULT_SYSTEM_PROMPT.to_string(),
            tools,
        })
    }

    pub async fn run(&self, user_prompt: String, progress_tx: Option<mpsc::UnboundedSender<Vec<Message>>>) -> Result<Vec<Message>> {
        let mut messages = vec![Message::User {
            content: rig::OneOrMany::one(UserContent::Text(rig::message::Text {
                text: user_prompt,
            })),
        }];

        info!("Starting agent run with model: {}", self.model);

        for turn in 0..MAX_TURNS {
            info!("Turn {}/{}", turn + 1, MAX_TURNS);

            // create completion request
            let request = CompletionRequest {
                preamble: Some(self.system_prompt.clone()),
                chat_history: rig::OneOrMany::many(messages.clone())
                    .context("Failed to create chat history")?,
                documents: vec![],
                tools: self.tools.clone(),
                temperature: Some(0.7),
                max_tokens: Some(4096),
                additional_params: None,
            };

            // call LLM
            let completion_model = self.anthropic_client.completion_model(&self.model);
            let response = completion_model
                .completion(request)
                .await
                .context("Failed to get completion from LLM")?;

            // extract assistant message
            let assistant_message = Message::Assistant {
                id: None,
                content: response.choice.clone(),
            };
            messages.push(assistant_message);

            // send progress update after adding assistant message
            if let Some(ref tx) = progress_tx {
                let _ = tx.send(messages.clone());
            }

            // check for tool calls
            let tool_calls: Vec<ToolCall> = response
                .choice
                .iter()
                .filter_map(|content| match content {
                    AssistantContent::ToolCall(call) => {
                        info!(
                            "Tool call detected: {} with args: {}",
                            call.function.name,
                            serde_json::to_string(&call.function.arguments).unwrap_or_default()
                        );
                        Some(call.clone())
                    }
                    AssistantContent::Text(text) => {
                        info!("Assistant: {}", text.text);
                        None
                    }
                    AssistantContent::Reasoning(reasoning) => {
                        info!("Reasoning: {:?}", reasoning.reasoning);
                        None
                    }
                })
                .collect();

            if tool_calls.is_empty() {
                info!("No tool calls, finishing");
                break;
            }

            // execute tool calls
            info!("Executing {} tool call(s)", tool_calls.len());
            let tool_results = self.execute_tools(tool_calls).await?;

            // add tool results to messages as UserContent
            let user_content: Vec<UserContent> = tool_results
                .into_iter()
                .map(|result| UserContent::ToolResult(result))
                .collect();

            messages.push(Message::User {
                content: rig::OneOrMany::many(user_content)
                    .context("Failed to create tool results")?,
            });

            // send progress update after adding tool results
            if let Some(ref tx) = progress_tx {
                let _ = tx.send(messages.clone());
            }
        }

        Ok(messages)
    }

    async fn execute_tools(&self, tool_calls: Vec<ToolCall>) -> Result<Vec<ToolResult>> {
        let mut results = Vec::new();

        for call in tool_calls {
            // skip invalid tool names (like $FUNCTION which is a placeholder)
            if call.function.name.starts_with('$') {
                warn!(
                    "Skipping invalid tool name: {} - this appears to be a placeholder",
                    call.function.name
                );
                let result_content = ToolResultContent::Text(rig::message::Text {
                    text: format!(
                        "Error: Invalid tool name '{}'. This appears to be a placeholder or invalid tool call.",
                        call.function.name
                    ),
                });
                results.push(ToolResult {
                    id: call.id,
                    call_id: call.call_id,
                    content: rig::OneOrMany::one(result_content),
                });
                continue;
            }

            info!(
                "Calling tool: {} with args: {}",
                call.function.name,
                serde_json::to_string(&call.function.arguments).unwrap_or_default()
            );

            let result_content = match self
                .mcp_client
                .call_tool(&call.function.name, call.function.arguments.clone())
                .await
            {
                Ok(content) => {
                    info!("Tool {} succeeded", call.function.name);
                    ToolResultContent::Text(rig::message::Text { text: content })
                }
                Err(e) => {
                    warn!("Tool {} failed: {}", call.function.name, e);
                    ToolResultContent::Text(rig::message::Text {
                        text: format!("Error calling tool '{}': {:#}", call.function.name, e),
                    })
                }
            };

            results.push(ToolResult {
                id: call.id,
                call_id: call.call_id,
                content: rig::OneOrMany::one(result_content),
            });
        }

        Ok(results)
    }
}
