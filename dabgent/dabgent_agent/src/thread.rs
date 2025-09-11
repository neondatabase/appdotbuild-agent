use crate::{handler::Handler, llm::CompletionResponse};
use rig::completion::Message;
use serde::{Deserialize, Serialize};

/// Enhanced thread state with specific waiting states
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum State {
    /// Initial state
    None,
    
    /// User states
    User,
    UserWait(UserWaitType),
    
    /// Agent states
    Agent,
    Tool,
    
    /// Terminal states
    Done,
    Fail(String),
}

impl Default for State {
    fn default() -> Self {
        State::None
    }
}

/// Specific types of user waiting states
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum UserWaitType {
    /// General text input
    Text,
    
    /// Multiple choice selection
    MultiChoice {
        prompt: String,
        options: Vec<String>,
        allow_multiple: bool,
    },
    
    /// Single choice selection (dropdown)
    SingleChoice {
        prompt: String,
        options: Vec<String>,
    },
    
    /// Yes/No confirmation
    Confirmation {
        prompt: String,
    },
    
    /// Clarification needed
    Clarification {
        question: String,
        context: Option<String>,
    },
    
    /// Continue after max tokens
    ContinueGeneration {
        reason: String,
    },
}

/// Enhanced thread with richer state information
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Thread {
    pub state: State,
    pub messages: Vec<Message>,
    pub done_call_id: Option<String>,
    pub metadata: ThreadMetadata,
}

/// Additional metadata for the thread
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ThreadMetadata {
    pub total_tokens: usize,
    pub last_model: Option<String>,
    pub tool_calls_count: usize,
    pub clarifications_requested: usize,
}

impl Thread {
    pub fn new() -> Self {
        Self {
            state: State::None,
            messages: Vec::new(),
            done_call_id: None,
            metadata: ThreadMetadata::default(),
        }
    }

    pub fn is_done(&self, response: &ToolResponse) -> bool {
        let Some(done_id) = &self.done_call_id else {
            return false;
        };
        response.content.iter().any(|item| {
            let rig::message::UserContent::ToolResult(res) = item else {
                return false;
            };
            res.id.eq(done_id) && res.content.iter().any(|tool| {
                matches!(tool, rig::message::ToolResultContent::Text(text) if text.text == "\"success\"")
            })
        })
    }

    pub fn update_done_call(&mut self, response: &CompletionResponse) {
        for item in response.choice.iter() {
            if let rig::message::AssistantContent::ToolCall(call) = item {
                if call.function.name == "done" {
                    self.done_call_id = Some(call.id.clone());
                }
            }
        }
    }

    pub fn has_tool_calls(response: &CompletionResponse) -> bool {
        response
            .choice
            .iter()
            .any(|item| matches!(item, rig::message::AssistantContent::ToolCall(..)))
    }

    /// Check if the response is requesting user input
    pub fn detect_user_wait_type(response: &CompletionResponse) -> Option<UserWaitType> {
        // Check for specific tool calls that indicate user interaction needed
        for item in response.choice.iter() {
            if let rig::message::AssistantContent::ToolCall(call) = item {
                match call.function.name.as_str() {
                    "request_multi_choice" => {
                        // Parse the arguments to get options
                        if let Ok(args) = serde_json::from_value::<MultiChoiceArgs>(call.function.arguments.clone()) {
                            return Some(UserWaitType::MultiChoice {
                                prompt: args.prompt,
                                options: args.options,
                                allow_multiple: args.allow_multiple.unwrap_or(false),
                            });
                        }
                    }
                    "request_clarification" => {
                        if let Ok(args) = serde_json::from_value::<ClarificationArgs>(call.function.arguments.clone()) {
                            return Some(UserWaitType::Clarification {
                                question: args.question,
                                context: args.context,
                            });
                        }
                    }
                    "request_confirmation" => {
                        if let Ok(args) = serde_json::from_value::<ConfirmationArgs>(call.function.arguments.clone()) {
                            return Some(UserWaitType::Confirmation {
                                prompt: args.prompt,
                            });
                        }
                    }
                    _ => {}
                }
            }
        }
        
        // Check if it hit token limit based on finish reason
        if response.finish_reason == crate::llm::FinishReason::MaxTokens {
            return Some(UserWaitType::ContinueGeneration {
                reason: "Maximum token limit reached".to_string(),
            });
        }
        
        // Default to text input if no tool calls
        if !Self::has_tool_calls(response) {
            Some(UserWaitType::Text)
        } else {
            None
        }
    }
}

impl Handler for Thread {
    type Command = Command;
    type Event = Event;
    type Error = Error;

    fn process(&mut self, command: Self::Command) -> Result<Vec<Self::Event>, Self::Error> {
        match (&self.state, command) {
            (State::None | State::User, Command::Prompt(prompt)) => {
                Ok(vec![Event::Prompted(prompt)])
            }
            (State::User | State::Tool, Command::Completion(response)) => {
                Ok(vec![Event::LlmCompleted(response)])
            }
            (State::Agent, Command::Tool(response)) => {
                Ok(vec![Event::ToolCompleted(response)])
            }
            (State::UserWait(_), Command::UserResponse(response)) => {
                Ok(vec![Event::UserResponded(response)])
            }
            (state, command) => Err(Error::Other(format!(
                "Invalid command {command:?} for state {state:?}"
            ))),
        }
    }

    fn fold(events: &[Self::Event]) -> Self {
        let mut thread = Self::new();
        for event in events {
            match event {
                Event::Prompted(prompt) => {
                    thread.state = State::User;
                    thread.messages.push(rig::message::Message::user(prompt));
                }
                Event::LlmCompleted(response) => {
                    // Update metadata
                    thread.metadata.total_tokens += response.output_tokens as usize;
                    
                    // Detect the appropriate state
                    if let Some(wait_type) = Thread::detect_user_wait_type(response) {
                        thread.state = State::UserWait(wait_type);
                    } else if Thread::has_tool_calls(response) {
                        thread.state = State::Agent;
                        thread.metadata.tool_calls_count += 1;
                    } else {
                        thread.state = State::UserWait(UserWaitType::Text);
                    }
                    
                    thread.update_done_call(response);
                    thread.messages.push(response.message());
                }
                Event::ToolCompleted(response) => {
                    thread.state = match thread.is_done(response) {
                        true => State::Done,
                        false => State::Tool,
                    };
                    thread.messages.push(response.message());
                }
                Event::UserResponded(response) => {
                    thread.state = State::User;
                    thread.messages.push(rig::message::Message::user(response.content.clone()));
                }
            }
        }
        thread
    }
}

/// Enhanced command enum with user response
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Command {
    Prompt(String),
    Completion(CompletionResponse),
    Tool(ToolResponse),
    UserResponse(UserResponse),
}

/// User response to various wait states
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserResponse {
    pub content: String,
    pub response_type: UserResponseType,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum UserResponseType {
    Text,
    MultiChoice(Vec<usize>), // Indices of selected options
    SingleChoice(usize),      // Index of selected option
    Confirmation(bool),
    Clarification,
}

/// Enhanced event enum with user response
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Event {
    Prompted(String),
    LlmCompleted(CompletionResponse),
    ToolCompleted(ToolResponse),
    UserResponded(UserResponse),
}

impl dabgent_mq::Event for Event {
    const EVENT_VERSION: &'static str = "2.0";

    fn event_type(&self) -> &'static str {
        match self {
            Event::Prompted(..) => "prompted",
            Event::LlmCompleted(..) => "llm_completed",
            Event::ToolCompleted(..) => "tool_completed",
            Event::UserResponded(..) => "user_responded",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolResponse {
    pub content: rig::OneOrMany<rig::message::UserContent>,
}

impl ToolResponse {
    pub fn message(&self) -> rig::completion::Message {
        rig::message::Message::User {
            content: self.content.clone(),
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("Agent error: {0}")]
    Other(String),
}

// Helper structs for parsing tool arguments
#[derive(Deserialize)]
struct MultiChoiceArgs {
    prompt: String,
    options: Vec<String>,
    allow_multiple: Option<bool>,
}

#[derive(Deserialize)]
struct ClarificationArgs {
    question: String,
    context: Option<String>,
}

#[derive(Deserialize)]
struct ConfirmationArgs {
    prompt: String,
}