from typing import Any, Annotated, Literal
from pydantic import BaseModel, Discriminator, Field, RootModel, Tag


class TextBlockModel(BaseModel):
    text: str


class ThinkingBlockModel(BaseModel):
    thinking: str
    signature: str


class ToolUseBlockModel(BaseModel):
    id: str
    name: str
    input: dict[str, Any]


class ToolResultBlockModel(BaseModel):
    tool_use_id: str
    content: str | list[dict[str, Any]] | None = None
    is_error: bool | None = None


def content_block_discriminator(v: Any) -> str:
    if isinstance(v, dict):
        if "tool_use_id" in v:
            return "tool_result"
        elif "thinking" in v and "signature" in v:
            return "thinking"
        elif "name" in v and "input" in v:
            return "tool_use"
        elif "text" in v:
            return "text"
    # Handle model instances
    if hasattr(v, "tool_use_id"):
        return "tool_result"
    elif hasattr(v, "thinking") and hasattr(v, "signature"):
        return "thinking"
    elif hasattr(v, "name") and hasattr(v, "input"):
        return "tool_use"
    elif hasattr(v, "text"):
        return "text"
    return "text"


ContentBlockModel = Annotated[
    Annotated[TextBlockModel, Tag("text")]
    | Annotated[ThinkingBlockModel, Tag("thinking")]
    | Annotated[ToolUseBlockModel, Tag("tool_use")]
    | Annotated[ToolResultBlockModel, Tag("tool_result")],
    Discriminator(content_block_discriminator),
]


class UserMessageModel(BaseModel):
    content: str | list[ContentBlockModel]
    parent_tool_use_id: str | None = None


class AssistantMessageModel(BaseModel):
    content: list[ContentBlockModel]
    model: str
    parent_tool_use_id: str | None = None
    error: str | None = None


class SystemMessageModel(BaseModel):
    subtype: str
    data: dict[str, Any]


class ResultMessageModel(BaseModel):
    subtype: str
    duration_ms: int
    duration_api_ms: int
    is_error: bool
    num_turns: int
    session_id: str
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None
    structured_output: Any = None


class StreamEventModel(BaseModel):
    uuid: str
    session_id: str
    event: dict[str, Any]
    parent_tool_use_id: str | None = None


def message_discriminator(v: Any) -> str:
    """Discriminator for Message based on distinctive fields."""
    if isinstance(v, dict):
        if "uuid" in v and "event" in v:
            return "stream"
        elif "duration_ms" in v and "duration_api_ms" in v:
            return "result"
        elif "model" in v and "content" in v:
            return "assistant"
        elif "content" in v:
            return "user"
        elif "subtype" in v and "data" in v:
            return "system"
    # Handle model instances
    if hasattr(v, "uuid") and hasattr(v, "event"):
        return "stream"
    elif hasattr(v, "duration_ms") and hasattr(v, "duration_api_ms"):
        return "result"
    elif hasattr(v, "model") and hasattr(v, "content"):
        return "assistant"
    elif hasattr(v, "content"):
        return "user"
    elif hasattr(v, "subtype") and hasattr(v, "data"):
        return "system"
    return "user"


MessageModel = Annotated[
    Annotated[UserMessageModel, Tag("user")]
    | Annotated[AssistantMessageModel, Tag("assistant")]
    | Annotated[SystemMessageModel, Tag("system")]
    | Annotated[ResultMessageModel, Tag("result")]
    | Annotated[StreamEventModel, Tag("stream")],
    Discriminator(message_discriminator),
]


class CmdPromptModel(BaseModel):
    type: Literal["prompt"] = "prompt"
    prompt: str
    config: dict[str, Any] | None = None


class CmdContinueModel(BaseModel):
    type: Literal["continue"] = "continue"


class CmdStopModel(BaseModel):
    type: Literal["stop"] = "stop"


CommandModel = RootModel[Annotated[CmdPromptModel | CmdContinueModel | CmdStopModel, Field(discriminator='type')]]


class EvtInterruptModel(BaseModel):
    type: Literal["interrupt"] = "interrupt"
    input_data: dict[str, Any]
    tool_use_id: str | None
    messages: list[MessageModel]


class EvtResultModel(BaseModel):
    type: Literal["result"] = "result"
    messages: list[MessageModel]


class EvtErrorModel(BaseModel):
    type: Literal["error"] = "error"
    detail: str


EventModel = RootModel[Annotated[EvtInterruptModel | EvtResultModel | EvtErrorModel, Field(discriminator='type')]]
