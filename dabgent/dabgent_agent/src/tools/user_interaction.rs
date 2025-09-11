use crate::toolbox::{Tool, ToolDyn};
use dabgent_sandbox::SandboxDyn;
use eyre::Result;
use rig::completion::ToolDefinition;
use serde::{Deserialize, Serialize};
use serde_json::json;

/// Tool for requesting multiple choice selection from user
#[derive(Debug, Clone)]
pub struct MultiChoiceTool;

#[derive(Debug, Serialize, Deserialize)]
pub struct MultiChoiceArgs {
    pub prompt: String,
    pub options: Vec<String>,
    #[serde(default)]
    pub allow_multiple: bool,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct MultiChoiceOutput {
    pub status: String,
    pub wait_type: String,
}

impl Tool for MultiChoiceTool {
    type Args = MultiChoiceArgs;
    type Output = MultiChoiceOutput;
    type Error = String;

    fn name(&self) -> String {
        "request_multi_choice".to_string()
    }

    fn definition(&self) -> ToolDefinition {
        ToolDefinition {
            name: <Self as Tool>::name(self),
            description: "Request user to select from multiple options".to_string(),
            parameters: json!({
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The question or prompt for the user"
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of options for the user to choose from"
                    },
                    "allow_multiple": {
                        "type": "boolean",
                        "description": "Whether to allow multiple selections",
                        "default": false
                    }
                },
                "required": ["prompt", "options"]
            }),
        }
    }

    async fn call(
        &self,
        _args: Self::Args,
        _sandbox: &mut Box<dyn SandboxDyn>,
    ) -> Result<Result<Self::Output, Self::Error>> {
        // This returns immediately - the actual selection happens in the UI
        Ok(Ok(MultiChoiceOutput {
            status: "waiting_for_user".to_string(),
            wait_type: "multi_choice".to_string(),
        }))
    }
}

/// Tool for requesting clarification from user
#[derive(Debug, Clone)]
pub struct ClarificationTool;

#[derive(Debug, Serialize, Deserialize)]
pub struct ClarificationArgs {
    pub question: String,
    pub context: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ClarificationOutput {
    pub status: String,
    pub wait_type: String,
}

impl Tool for ClarificationTool {
    type Args = ClarificationArgs;
    type Output = ClarificationOutput;
    type Error = String;

    fn name(&self) -> String {
        "request_clarification".to_string()
    }

    fn definition(&self) -> ToolDefinition {
        ToolDefinition {
            name: <Self as Tool>::name(self),
            description: "Request clarification from the user when something is unclear".to_string(),
            parameters: json!({
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The clarification question"
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional context about what needs clarification"
                    }
                },
                "required": ["question"]
            }),
        }
    }

    async fn call(
        &self,
        _args: Self::Args,
        _sandbox: &mut Box<dyn SandboxDyn>,
    ) -> Result<Result<Self::Output, Self::Error>> {
        Ok(Ok(ClarificationOutput {
            status: "waiting_for_user".to_string(),
            wait_type: "clarification".to_string(),
        }))
    }
}

/// Tool for requesting confirmation from user
#[derive(Debug, Clone)]
pub struct ConfirmationTool;

#[derive(Debug, Serialize, Deserialize)]
pub struct ConfirmationArgs {
    pub prompt: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ConfirmationOutput {
    pub status: String,
    pub wait_type: String,
}

impl Tool for ConfirmationTool {
    type Args = ConfirmationArgs;
    type Output = ConfirmationOutput;
    type Error = String;

    fn name(&self) -> String {
        "request_confirmation".to_string()
    }

    fn definition(&self) -> ToolDefinition {
        ToolDefinition {
            name: <Self as Tool>::name(self),
            description: "Request yes/no confirmation from the user".to_string(),
            parameters: json!({
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The confirmation prompt"
                    }
                },
                "required": ["prompt"]
            }),
        }
    }

    async fn call(
        &self,
        _args: Self::Args,
        _sandbox: &mut Box<dyn SandboxDyn>,
    ) -> Result<Result<Self::Output, Self::Error>> {
        Ok(Ok(ConfirmationOutput {
            status: "waiting_for_user".to_string(),
            wait_type: "confirmation".to_string(),
        }))
    }
}

/// Tool for indicating need to continue generation after hitting token limit
#[derive(Debug, Clone)]
pub struct ContinueTool;

#[derive(Debug, Serialize, Deserialize)]
pub struct ContinueArgs {
    pub reason: String,
    pub progress_summary: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ContinueOutput {
    pub status: String,
    pub need_continuation: bool,
}

impl Tool for ContinueTool {
    type Args = ContinueArgs;
    type Output = ContinueOutput;
    type Error = String;

    fn name(&self) -> String {
        "continue_generation".to_string()
    }

    fn definition(&self) -> ToolDefinition {
        ToolDefinition {
            name: <Self as Tool>::name(self),
            description: "Indicate that generation needs to continue due to length limits".to_string(),
            parameters: json!({
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Why continuation is needed"
                    },
                    "progress_summary": {
                        "type": "string",
                        "description": "Summary of progress so far"
                    }
                },
                "required": ["reason"]
            }),
        }
    }

    async fn call(
        &self,
        _args: Self::Args,
        _sandbox: &mut Box<dyn SandboxDyn>,
    ) -> Result<Result<Self::Output, Self::Error>> {
        Ok(Ok(ContinueOutput {
            status: "need_continuation".to_string(),
            need_continuation: true,
        }))
    }
}

/// Create a toolset with user interaction tools
pub fn user_interaction_tools() -> Vec<Box<dyn ToolDyn>> {
    vec![
        Box::new(MultiChoiceTool),
        Box::new(ClarificationTool),
        Box::new(ConfirmationTool),
        Box::new(ContinueTool),
    ]
}

/// Combine user interaction tools with existing tools
pub fn with_user_interaction(mut tools: Vec<Box<dyn ToolDyn>>) -> Vec<Box<dyn ToolDyn>> {
    tools.extend(user_interaction_tools());
    tools
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_multi_choice_tool_definition() {
        let tool = MultiChoiceTool;
        let definition = <MultiChoiceTool as Tool>::definition(&tool);
        
        assert_eq!(definition.name, "request_multi_choice");
        assert_eq!(definition.description, "Request user to select from multiple options");
        
        // Verify parameters structure
        let params = definition.parameters.as_object().unwrap();
        assert_eq!(params["type"], "object");
        assert!(params["properties"].as_object().is_some());
        assert!(params["required"].as_array().unwrap().contains(&serde_json::json!("prompt")));
        assert!(params["required"].as_array().unwrap().contains(&serde_json::json!("options")));
    }

    #[tokio::test]
    async fn test_clarification_tool_definition() {
        let tool = ClarificationTool;
        let definition = <ClarificationTool as Tool>::definition(&tool);
        
        assert_eq!(definition.name, "request_clarification");
        assert_eq!(definition.description, "Request clarification from the user when something is unclear");
        
        // Verify parameters structure
        let params = definition.parameters.as_object().unwrap();
        assert_eq!(params["type"], "object");
        assert!(params["properties"].as_object().is_some());
        assert!(params["required"].as_array().unwrap().contains(&serde_json::json!("question")));
    }

    #[tokio::test]
    async fn test_confirmation_tool_definition() {
        let tool = ConfirmationTool;
        let definition = <ConfirmationTool as Tool>::definition(&tool);
        
        assert_eq!(definition.name, "request_confirmation");
        assert_eq!(definition.description, "Request yes/no confirmation from the user");
        
        // Verify parameters structure
        let params = definition.parameters.as_object().unwrap();
        assert_eq!(params["type"], "object");
        assert!(params["properties"].as_object().is_some());
        assert!(params["required"].as_array().unwrap().contains(&serde_json::json!("prompt")));
    }
}