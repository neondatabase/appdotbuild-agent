from typing import Literal, Protocol, Self, Iterable, TypedDict, TypeAlias, Union, Required, NotRequired
from dataclasses import dataclass
import hashlib

@dataclass
class TextRaw:
    text: str


@dataclass
class ToolUse:
    name: str
    input: object
    id: str | None = None


@dataclass
class ToolResult:
    content: str
    tool_use_id: str | None = None
    name: str | None = None
    is_error: bool | None = None


@dataclass
class ThinkingBlock:
    thinking: str


@dataclass
class ToolUseResult:
    tool_use: ToolUse
    tool_result: ToolResult

    @classmethod
    def from_tool_use(cls, tool_use: ToolUse, content: str, is_error: bool | None = None) -> "ToolUseResult":
        return cls(tool_use, ToolResult(content, tool_use.id, tool_use.name, is_error))


@dataclass
class AttachedFiles:
    files: list[str]
    _cache_key: str | None = None

    @property
    def cache_key(self) -> str:
        if self._cache_key is None:
            return hashlib.md5("".join(sorted(self.files)).encode()).hexdigest()
        return self._cache_key


ContentBlock: TypeAlias = Union[TextRaw, ToolUse, ToolUseResult, ThinkingBlock]


def dump_content(content: Iterable[ContentBlock]) -> list[dict]:
    result = []
    for block in content:
        match block:
            case TextRaw(text):
                result.append({"type": "text", "text": text})
            case ToolUse(name, input, id):
                result.append({"type": "tool_use", "name": name, "input": input, "id": id})
            case ThinkingBlock(thinking):
                result.append({"type": "thinking", "thinking": thinking})
            case ToolUseResult(tool_use, tool_result):
                result.append({
                    "type": "tool_use_result",
                    "tool_use": {
                        "name": tool_use.name,
                        "input": tool_use.input,
                        "id": tool_use.id,
                    },
                    "tool_result": {
                        "content": tool_result.content,
                        "name": tool_result.name,
                        "is_error": tool_result.is_error,
                    },
                })
    return result


def load_content(data: list[dict]) -> list[ContentBlock]:
    content = []
    for block in data:
        match block:
            case {"type": "text", "text": text}:
                content.append(TextRaw(text))
            case {"type": "tool_use", "name": name, "input": input, "id": id}:
                content.append(ToolUse(name, input, id))
            case {"type": "thinking", "thinking": thinking}:
                content.append(ThinkingBlock(thinking))
            case {"type": "tool_use_result", "tool_use": tool_use, "tool_result": tool_result}:
                content.append(ToolUseResult(
                    ToolUse(tool_use["name"], tool_use["input"], tool_use["id"]),
                    ToolResult(tool_result["content"], tool_result["name"], tool_result["is_error"])
                ))
            case _:
                raise ValueError(f"Unknown block type in content: {block}")
    return content


@dataclass
class InternalMessage:
    role: Literal["user", "assistant"]
    content: Iterable[ContentBlock]

    def to_dict(self) -> dict:
        return {"role": self.role, "content": dump_content(self.content)}

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        return cls(data["role"], load_content(data["content"]))


@dataclass
class Completion:
    role: Literal["assistant"]
    content: Iterable[ContentBlock]
    input_tokens: int
    output_tokens: int
    stop_reason: Literal["end_turn", "max_tokens", "stop_sequence", "tool_use", "unknown"]
    thinking_tokens: int | None = None

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": dump_content(self.content),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "stop_reason": self.stop_reason,
            "thinking_tokens": self.thinking_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        return cls(
            data["role"],
            load_content(data["content"]),
            data["input_tokens"],
            data["output_tokens"],
            data["stop_reason"],
            data.get("thinking_tokens"),
        )


class Tool(TypedDict, total=False):
    name: Required[str]
    description: str
    input_schema: Required[dict[str, object]]
    cache_control: NotRequired[dict[str, str]]


# TODO: remove this alias after all clients are updated
Message = InternalMessage

# ----------------------------------
# Async LLM protocol
# ----------------------------------

class AsyncLLM(Protocol):
    async def completion(
        self,
        messages: list[Message],
        max_tokens: int,
        model: str | None = None,
        temperature: float = 1.0,
        tools: list[Tool] | None = None,
        tool_choice: str | None = None,
        system_prompt: str | None = None,
        *args,
        **kwargs,
    ) -> Completion:
        ...
