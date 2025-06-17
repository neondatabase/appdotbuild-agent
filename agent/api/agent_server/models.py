"""
Pydantic models for the agent server API.

These models define the data structures for API requests and responses,
ensuring consistency with the API specification in `agent_api.tsp`.
They are used by the `async_server.py` for data validation.

Refer to `architecture.puml` for context within the system.
"""
from enum import Enum
import ujson as json
from typing import Dict, List, Optional, Any, Union, Literal, Type, TypeVar
from pydantic import BaseModel, Field


T = TypeVar('T', bound='BaseModel')


class AgentStatus(str, Enum):
    """Defines the status of the Agent Server during processing."""
    RUNNING = "running"
    IDLE = "idle"


class MessageKind(str, Enum):
    """Defines the type of message being sent from the Agent Server."""
    STAGE_RESULT = "StageResult"  # tool was used, and FSM state is expected to be updated
    RUNTIME_ERROR = "RuntimeError"  #  things went wrong!
    REFINEMENT_REQUEST = "RefinementRequest"  # no tool was used, meaning the agent is asking for more information
    REVIEW_RESULT = "ReviewResult"  # generation completed successfully
    KEEP_ALIVE = "KeepAlive"  # empty event to keep the connection alive


class UserMessage(BaseModel):
    """Represents a message from the user to the agent."""
    role: Literal["user"] = Field("user", description="Fixed field for client to detect user message in the history")
    content: str = Field(..., description="The content of the user's message.")
    
    def to_json(self) -> str:
        """Serialize the model to JSON string."""
        return self.model_dump_json(by_alias=True)
    
    @classmethod
    def from_json(cls: Type[T], json_str: str) -> T:
        """Deserialize a JSON string to a model instance."""
        return cls.model_validate(json.loads(json_str))


class DiffStatEntry(BaseModel):
    """Summary information about a single file modified in the current step."""

    path: str = Field(..., description="Path of the file that changed (relative to the project root).")
    insertions: int = Field(..., description="Number of lines inserted in this file during the current step.")
    deletions: int = Field(..., description="Number of lines deleted in this file during the current step.")

class ExternalContentBlock(BaseModel):
    """Represents a single content block in an external message."""
    role: Literal["assistant"] = Field("assistant", description="Deprecated. The role of the block. Will be removed in the future.")
    content: str = Field(..., description="The content of the block.")
    #timestamp: datetime.datetime = Field(..., description="The timestamp of the block.")

class AgentMessage(BaseModel):
    """The detailed message payload from the agent."""
    role: Literal["assistant"] = Field("assistant", description="Fixed field for client to detect assistant message in the history") 
    kind: MessageKind = Field(..., description="The type of message being sent.")
    messages: Optional[List[ExternalContentBlock]] = Field(
        None,
        description="Structured content blocks. Present only for new clients.")
    agent_state: Optional[Dict[str, Any]] = Field(
        None, 
        alias="agentState", 
        description="Updated state of the Agent Server for the next request."
    )
    unified_diff: Optional[str] = Field(
        None, 
        alias="unifiedDiff", 
        description="A unified diff format string representing code changes made by the agent."
    )
    complete_diff_hash: Optional[str] = Field(
        None,
        alias="completeDiffHash",
        description="Hash (e.g., SHA-256) of the complete unified diff for the current application state."
    )
    diff_stat: Optional[List[DiffStatEntry]] = Field(
        None,
        alias="diffStat",
        description="Lightweight per-file summary of changes since the previous message."
    )
    app_name: Optional[str] = Field(
        None,
        description="Generated application name suitable for use as a GitHub repository name."
    )
    commit_message: Optional[str] = Field(
        None,
        description="Generated commit message suitable for use in Git commits."
    )
    
    def to_json(self) -> str:
        """Serialize the model to JSON string."""
        return self.model_dump_json(by_alias=True)
    
    @classmethod
    def from_json(cls: Type[T], json_str: str) -> T:
        """Deserialize a JSON string to a model instance."""
        return cls.model_validate(json.loads(json_str))


ConversationMessage = Union[UserMessage, AgentMessage]


def parse_conversation_message(json_str: str) -> ConversationMessage:
    """Parse a JSON string into the appropriate ConversationMessage type."""
    data = json.loads(json_str)
    if data.get("role") == "user":
        return UserMessage.model_validate(data)
    elif data.get("role") == "assistant":
        return AgentMessage.model_validate(data)
    else:
        raise ValueError(f"Unknown role in message: {data.get('role')}")


class AgentSseEvent(BaseModel):
    """Structure of the data payload within each Server-Sent Event (SSE)."""
    status: AgentStatus = Field(..., description="Current status of the agent (running or idle).")
    trace_id: Optional[str] = Field(None, alias="traceId", description="The trace ID corresponding to the POST request.")
    message: AgentMessage = Field(..., description="The detailed message payload from the agent.")
    
    def to_json(self) -> str:
        """Serialize the model to JSON string."""
        return self.model_dump_json(by_alias=True)
    
    @classmethod
    def from_json(cls: Type[T], json_str: str) -> T:
        """Deserialize a JSON string to a model instance."""
        return cls.model_validate(json.loads(json_str))


class FileEntry(BaseModel):
    """Represents a single file with its path and content."""
    path: str = Field(..., description="The relative path of the file.")
    content: str = Field(..., description="The content of the file.")


class AgentRequest(BaseModel):
    """Request body for initiating or continuing interaction with the Agent Server."""
    all_messages: List[ConversationMessage] = Field(..., alias="allMessages", description="History of all messages in the current conversation thread.")
    application_id: str = Field(..., alias="applicationId", description="Unique identifier for the application instance.")
    trace_id: str = Field(..., alias="traceId", description="Unique identifier for this request/response cycle.")
    all_files: Optional[List[FileEntry]] = Field(None, alias="allFiles", description="All files in the workspace to be used for diff generation.")
    template_id: Optional[str] = Field(None, alias="templateId", description="Unique identifier of the template the agent supports.")
    agent_state: Optional[Dict[str, Any]] = Field(
        None, 
        alias="agentState", 
        description="The full state of the Agent Server to restore from."
    )
    settings: Optional[Dict[str, Any]] = Field(
        None, 
        description="Settings for the agent execution, such as maximum number of iterations."
    )
    
    def to_json(self) -> str:
        """Serialize the model to JSON string."""
        return self.model_dump_json(by_alias=True)
    
    @classmethod
    def from_json(cls: Type[T], json_str: str) -> T:
        """Deserialize a JSON string to a model instance."""
        return cls.model_validate(json.loads(json_str))


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str
    details: Optional[str] = None
    
    def to_json(self) -> str:
        """Serialize the model to JSON string."""
        return self.model_dump_json()
    
    @classmethod
    def from_json(cls: Type[T], json_str: str) -> T:
        """Deserialize a JSON string to a model instance."""
        return cls.model_validate(json.loads(json_str))


def format_internal_message_for_display(message) -> str:
    """
    Convert an InternalMessage to user-friendly display format.
    
    Args:
        message: InternalMessage object to format
        
    Returns:
        User-friendly string representation
    """
    # Tool name to user-friendly description mapping
    tool_descriptions = {
        "start_fsm": "🚀 Starting application development",
        "create_file": "📄 Creating file",
        "edit_file": "✏️  Editing file", 
        "read_file": "📖 Reading file",
        "run_command": "⚡ Running command",
        "install_dependencies": "📦 Installing dependencies",
        "build_project": "🔨 Building project",
        "test_project": "🧪 Running tests",
        "deploy_project": "🌐 Deploying project",
        "analyze_code": "🔍 Analyzing code",
        "fix_errors": "🔧 Fixing errors",
        "validate_schema": "✅ Validating schema",
        "generate_code": "⚙️  Generating code",
        "refactor_code": "🔄 Refactoring code",
        "optimize_performance": "⚡ Optimizing performance",
        "setup_database": "🗄️  Setting up database",
        "migrate_database": "🔄 Migrating database",
        "backup_data": "💾 Backing up data",
        "restore_data": "📥 Restoring data",
        "configure_environment": "⚙️  Configuring environment",
        "setup_ci_cd": "🔄 Setting up CI/CD",
        "security_scan": "🔒 Running security scan",
        "lint_code": "✨ Linting code",
        "format_code": "💅 Formatting code",
    }
    
    parts = []
    for block in message.content:
        block_type = type(block).__name__
        
        if block_type == "TextRaw":
            parts.append(block.text)
        elif block_type == "ToolUse":
            # Use friendly description if available, otherwise format the name nicely
            name = block.name
            if name in tool_descriptions:
                description = tool_descriptions[name]
            else:
                # Convert snake_case to Title Case for unknown tools
                description = f"🔧 {name.replace('_', ' ').title()}"
            
            parts.append(description)
            
            # Add relevant context from input in a user-friendly way
            input_data = block.input
            if input_data and isinstance(input_data, dict):
                context_parts = []
                
                # Extract meaningful information based on common input patterns
                if "app_description" in input_data:
                    context_parts.append(f"Building: {input_data['app_description']}")
                elif "file_path" in input_data or "path" in input_data:
                    file_path = input_data.get("file_path") or input_data.get("path")
                    context_parts.append(f"File: {file_path}")
                elif "command" in input_data:
                    context_parts.append(f"Command: {input_data['command']}")
                elif "content" in input_data and len(str(input_data['content'])) < 250:
                    context_parts.append(f"Content: {input_data['content']}")
                elif "query" in input_data:
                    context_parts.append(f"Query: {input_data['query']}")
                elif "message" in input_data:
                    context_parts.append(f"Message: {input_data['message']}")
                
                if context_parts:
                    parts.append(f"  {' | '.join(context_parts)}")
                    
        elif block_type == "ToolUseResult":
            tool_use = block.tool_use
            tool_result = block.tool_result
            
            if tool_result.is_error:
                parts.append(f"❌ Error in {tool_use.name}: {tool_result.content}")
            else:
                # For successful tool results, show a brief success message
                tool_name = tool_use.name
                if tool_name in tool_descriptions:
                    base_desc = tool_descriptions[tool_name].replace("🚀 Starting", "✅ Started").replace("📄 Creating", "✅ Created").replace("✏️  Editing", "✅ Edited").replace("⚡ Running", "✅ Completed")
                    parts.append(base_desc)
                else:
                    parts.append(f"✅ {tool_name.replace('_', ' ').title()} completed")
                
                # Show brief result summary if content is short and meaningful
                if tool_result.content and len(tool_result.content.strip()) < 200:
                    content_preview = tool_result.content.strip()
                    if not content_preview.startswith(('{"', '[', '<')):  # Skip JSON/XML/HTML output
                        parts.append(f"  → {content_preview}")
        elif block_type == "ThinkingBlock":
            # Skip thinking blocks for external display
            pass
    
    return "\n".join(parts).strip()
