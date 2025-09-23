use rig::{client::CompletionClient, completion::CompletionModel};
use serde::{Deserialize, Serialize};
use std::pin::Pin;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Completion {
    /// The model to be used for the completion
    pub model: String,
    /// The last message to be sent to the completion model provider
    pub prompt: rig::message::Message,
    /// The system prompt to be sent to the completion model provider
    pub preamble: Option<String>,
    /// The chat history to be sent to the completion model provider
    pub history: Vec<rig::message::Message>,
    /// The tools to be sent to the completion model provider
    pub tools: Vec<rig::completion::ToolDefinition>,
    /// The temperature to be sent to the completion model provider
    pub temperature: Option<f64>,
    /// The max tokens to be sent to the completion model provider
    pub max_tokens: Option<u64>,
    /// Additional provider-specific parameters to be sent to the completion model provider
    pub additional_params: Option<serde_json::Value>,
}

impl Completion {
    pub fn new(model: String, prompt: rig::message::Message) -> Self {
        Self {
            model,
            prompt,
            preamble: None,
            history: Vec::new(),
            tools: Vec::new(),
            temperature: None,
            max_tokens: None,
            additional_params: None,
        }
    }

    pub fn preamble(mut self, preamble: String) -> Self {
        self.preamble = Some(preamble);
        self
    }

    pub fn tools(mut self, tools: Vec<rig::completion::ToolDefinition>) -> Self {
        self.tools = tools;
        self
    }

    pub fn history(mut self, history: Vec<rig::message::Message>) -> Self {
        self.history = history;
        self
    }

    pub fn temperature(mut self, temperature: f64) -> Self {
        self.temperature = Some(temperature);
        self
    }

    pub fn max_tokens(mut self, max_tokens: u64) -> Self {
        self.max_tokens = Some(max_tokens);
        self
    }

    pub fn additional_params(mut self, additional_params: serde_json::Value) -> Self {
        self.additional_params = Some(additional_params);
        self
    }
}

impl std::convert::From<Completion> for rig::completion::CompletionRequest {
    fn from(completion: Completion) -> Self {
        let history = rig::OneOrMany::many([completion.history, vec![completion.prompt]].concat())
            .expect("There will always be atleast the prompt");
        rig::completion::CompletionRequest {
            preamble: completion.preamble,
            chat_history: history,
            documents: Vec::new(),
            tools: completion.tools,
            temperature: completion.temperature,
            max_tokens: completion.max_tokens,
            additional_params: completion.additional_params,
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CompletionResponse {
    pub choice: rig::OneOrMany<rig::message::AssistantContent>,
    pub finish_reason: FinishReason,
    pub output_tokens: u64,
}

impl CompletionResponse {
    pub fn message(&self) -> rig::message::Message {
        rig::message::Message::Assistant {
            id: None,
            content: self.choice.clone(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub enum FinishReason {
    None,
    Stop,
    MaxTokens,
    ToolUse,
    Other(String),
}

pub trait LLMClient: Clone + Send + Sync {
    fn completion(
        &self,
        completion: Completion,
    ) -> impl Future<Output = eyre::Result<CompletionResponse>> + Send;

    fn boxed(self) -> Box<dyn LLMClientDyn>
    where
        Self: Sized + 'static,
    {
        Box::new(self)
    }
}

pub trait LLMClientDyn: Send + Sync {
    fn completion(
        &self,
        completion: Completion,
    ) -> Pin<Box<dyn Future<Output = eyre::Result<CompletionResponse>> + Send + '_>>;
}

impl<T: LLMClient> LLMClientDyn for T {
    fn completion(
        &self,
        completion: Completion,
    ) -> Pin<Box<dyn Future<Output = eyre::Result<CompletionResponse>> + Send + '_>> {
        Box::pin(self.completion(completion))
    }
}

impl LLMClient for rig::providers::anthropic::Client {
    async fn completion(&self, completion: Completion) -> eyre::Result<CompletionResponse> {
        let model = self.completion_model(&completion.model);
        let result = model.completion(completion.into()).await.map(|response| {
            let finish_reason = response.raw_response.stop_reason;
            let finish_reason =
                finish_reason.map_or(FinishReason::None, |reason| match reason.as_ref() {
                    "end_turn" => FinishReason::Stop,
                    "max_tokens" => FinishReason::MaxTokens,
                    "tool_use" => FinishReason::ToolUse,
                    _ => FinishReason::Other(reason),
                });
            CompletionResponse {
                choice: response.choice,
                finish_reason,
                output_tokens: response.raw_response.usage.output_tokens,
            }
        });
        result.map_err(Into::into)
    }
}

impl LLMClient for rig::providers::gemini::Client {
    async fn completion(&self, completion: Completion) -> eyre::Result<CompletionResponse> {
        use rig::providers::gemini::completion::gemini_api_types::{self};
        let model = self.completion_model(&completion.model);
        let generation_config = gemini_api_types::GenerationConfig {
            temperature: completion.temperature,
            max_output_tokens: completion.max_tokens,
            ..Default::default()
        };
        let cfg = gemini_api_types::AdditionalParameters {
            generation_config,
            additional_params: completion.additional_params.clone(),
        };
        let completion = Completion {
            additional_params: Some(serde_json::to_value(cfg).unwrap()),
            ..completion
        };
        let result = model.completion(completion.into()).await.map(|response| {
            let finish_reason = response.raw_response.candidates[0].finish_reason.as_ref();
            let mut finish_reason = finish_reason.map_or(FinishReason::None, |reason| match reason {
                gemini_api_types::FinishReason::Stop => FinishReason::Stop,
                gemini_api_types::FinishReason::MaxTokens => FinishReason::MaxTokens,
                _ => FinishReason::Other(format!("{reason:?}")),
            });
            // If the model emitted tool calls, treat finish as ToolUse to drive the tool executor
            if response
                .choice
                .iter()
                .any(|c| matches!(c, &rig::message::AssistantContent::ToolCall(..)))
            {
                finish_reason = FinishReason::ToolUse;
            }
            let output_tokens = response
                .raw_response
                .usage_metadata
                .map_or(0, |x| x.candidates_token_count as u64);
            CompletionResponse {
                choice: response.choice,
                finish_reason,
                output_tokens,
            }
        });
        result.map_err(Into::into)
    }
}
