use rig::{client::CompletionClient, completion::CompletionModel};
use serde::{Deserialize, Serialize};
use std::pin::Pin;
use std::time::Duration;
use tokio::time::sleep;

const MAX_COMPLETION_ATTEMPTS: usize = 4;
const BASE_BACKOFF_MS: u64 = 250;
const MAX_BACKOFF_MS: u64 = 5000;

fn backoff_delay_ms(attempt: usize) -> u64 {
    let exp = BASE_BACKOFF_MS.saturating_mul(1 << (attempt.saturating_sub(1)));
    exp.min(MAX_BACKOFF_MS)
}

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

#[derive(Clone)]
pub struct RetryingLLM<C: LLMClient> {
    inner: C,
    max_attempts: usize,
    jitter: bool,
}

impl<C: LLMClient> RetryingLLM<C> {
    pub fn new(inner: C) -> Self {
        Self {
            inner,
            max_attempts: MAX_COMPLETION_ATTEMPTS,
            jitter: true,
        }
    }

    pub fn with_max_attempts(mut self, max_attempts: usize) -> Self {
        self.max_attempts = max_attempts;
        self
    }

    pub fn with_jitter(mut self, jitter: bool) -> Self {
        self.jitter = jitter;
        self
    }
}

impl<C: LLMClient> LLMClient for RetryingLLM<C> {
    async fn completion(&self, completion: Completion) -> eyre::Result<CompletionResponse> {
        for attempt in 1..=self.max_attempts {
            match self.inner.completion(completion.clone()).await {
                Ok(resp) => return Ok(resp),
                Err(err) => {
                    if attempt < self.max_attempts {
                        let base = backoff_delay_ms(attempt);
                        let delay_ms = if self.jitter { jitter_ms(base) } else { base };
                        tracing::warn!(
                            attempt = attempt,
                            max_attempts = self.max_attempts,
                            delay_ms = delay_ms,
                            model = %completion.model,
                            error = %err,
                            "LLM completion failed, retrying with backoff"
                        );
                        sleep(Duration::from_millis(delay_ms)).await;
                        continue;
                    } else {
                        tracing::error!(
                            attempt = attempt,
                            max_attempts = self.max_attempts,
                            model = %completion.model,
                            error = %err,
                            "LLM completion failed, giving up"
                        );
                        return Err(err);
                    }
                }
            }
        }
        unreachable!()
    }
}

pub trait WithRetryExt: LLMClient + Sized {
    fn with_retry(self) -> RetryingLLM<Self> {
        RetryingLLM::new(self)
    }
}

impl<T: LLMClient> WithRetryExt for T {}

fn jitter_ms(base_ms: u64) -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    let nanos = now.subsec_nanos() as u64;
    // 50% - 150% jitter
    let pct = 50 + (nanos % 101);
    let jittered = base_ms.saturating_mul(pct).saturating_div(100);
    jittered.min(MAX_BACKOFF_MS)
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

impl LLMClient for rig::providers::openrouter::Client {
    async fn completion(&self, completion: Completion) -> eyre::Result<CompletionResponse> {
        let model = self.completion_model(&completion.model);
        let result = model.completion(completion.into()).await.map(|response| {
            let finish_reason = response.raw_response.choices[0].finish_reason.as_ref();
            // If the model emitted tool calls, treat finish as ToolUse to drive the tool executor
            let finish_reason = if response
                .choice
                .iter()
                .any(|c| matches!(c, &rig::message::AssistantContent::ToolCall(..)))
            {
                FinishReason::ToolUse
            } else {
                finish_reason.map_or(FinishReason::None, |reason| match reason.as_ref() {
                    "stop" => FinishReason::Stop,
                    "length" => FinishReason::MaxTokens,
                    "tool_calls" => FinishReason::ToolUse,
                    // Rest cases: actually either "content_filter" or "error" according to docs
                    _ => FinishReason::Other(reason.clone()),
                })
            };
            let output_tokens = response
                .raw_response
                .usage
                .map_or(0, |x| usize_to_u64(x.completion_tokens));
            CompletionResponse {
                choice: response.choice,
                finish_reason,
                output_tokens,
            }
        });
        result.map_err(Into::into)
    }
}

// TODO: consider placing in a common utils module
fn usize_to_u64(value: usize) -> u64 {
    // NOTE: Actually nope when optimized
    // NOTE: The raw cast "as" could be used instead but it might be more prone to errors in a common case
    value
        .try_into()
        .expect("usize to u64 conversion unexpectedly failed")
}
