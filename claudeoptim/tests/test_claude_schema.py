"""Test claude_schema serialization/deserialization."""

from dataclasses import asdict
from claude_agent_sdk.types import (
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
    UserMessage,
    AssistantMessage,
    SystemMessage,
    ResultMessage,
    StreamEvent,
)
from sbclaude.schema import (
    TextBlockModel,
    ThinkingBlockModel,
    ToolUseBlockModel,
    ToolResultBlockModel,
    UserMessageModel,
    AssistantMessageModel,
    SystemMessageModel,
    ResultMessageModel,
    StreamEventModel,
    MessageModel,
)
from pydantic import TypeAdapter


def test_text_block():
    """Test TextBlock serialization/deserialization."""
    text_block = TextBlock(text="Hello, world!")
    validated = TextBlockModel.model_validate(asdict(text_block))
    assert validated.text == "Hello, world!"


def test_thinking_block():
    """Test ThinkingBlock serialization/deserialization."""
    thinking_block = ThinkingBlock(thinking="Let me think...", signature="sig123")
    validated = ThinkingBlockModel.model_validate(asdict(thinking_block))
    assert validated.thinking == "Let me think..."
    assert validated.signature == "sig123"


def test_tool_use_block():
    """Test ToolUseBlock serialization/deserialization."""
    tool_use_dict = {"id": "tool_1", "name": "search", "input": {"query": "test"}}
    validated = ToolUseBlockModel.model_validate(tool_use_dict)
    assert validated.name == "search"
    assert validated.id == "tool_1"
    assert validated.input["query"] == "test"


def test_tool_result_block():
    """Test ToolResultBlock serialization/deserialization."""
    tool_result_dict = {"tool_use_id": "tool_1", "content": "Result", "is_error": False}
    validated = ToolResultBlockModel.model_validate(tool_result_dict)
    assert validated.tool_use_id == "tool_1"
    assert validated.content == "Result"
    assert validated.is_error is False


def test_user_message_string_content():
    """Test UserMessage with string content."""
    model: TypeAdapter[MessageModel] = TypeAdapter(MessageModel)

    user_msg = UserMessage(content="Hello Claude")
    validated = UserMessageModel.model_validate(asdict(user_msg))
    user_json = validated.model_dump_json()
    deserialized = model.validate_json(user_json)

    assert isinstance(deserialized, UserMessageModel)
    assert deserialized.content == "Hello Claude"


def test_user_message_blocks_content():
    """Test UserMessage with content blocks."""
    model: TypeAdapter[MessageModel] = TypeAdapter(MessageModel)

    user_msg_blocks = UserMessage(
        content=[TextBlock(text="Hello"), TextBlock(text="World")]
    )
    validated = UserMessageModel.model_validate(asdict(user_msg_blocks))
    user_msg_blocks_json = validated.model_dump_json()
    deserialized = model.validate_json(user_msg_blocks_json)

    assert isinstance(deserialized, UserMessageModel)
    assert isinstance(deserialized.content, list)
    assert len(deserialized.content) == 2


def test_assistant_message():
    """Test AssistantMessage serialization/deserialization."""
    model: TypeAdapter[MessageModel] = TypeAdapter(MessageModel)

    assistant_msg = AssistantMessage(
        content=[
            TextBlock(text="I'm thinking..."),
            ThinkingBlock(thinking="Deep thought", signature="sig456"),
        ],
        model="claude-3-5-sonnet-20241022",
    )
    validated = AssistantMessageModel.model_validate(asdict(assistant_msg))
    assistant_msg_json = validated.model_dump_json()
    deserialized = model.validate_json(assistant_msg_json)

    assert isinstance(deserialized, AssistantMessageModel)
    assert deserialized.model == "claude-3-5-sonnet-20241022"
    assert len(deserialized.content) == 2


def test_system_message():
    """Test SystemMessage serialization/deserialization."""
    model: TypeAdapter[MessageModel] = TypeAdapter(MessageModel)

    system_msg = SystemMessage(subtype="info", data={"key": "value"})
    validated = SystemMessageModel.model_validate(asdict(system_msg))
    system_msg_json = validated.model_dump_json()
    deserialized = model.validate_json(system_msg_json)

    assert isinstance(deserialized, SystemMessageModel)
    assert deserialized.subtype == "info"
    assert deserialized.data["key"] == "value"


def test_result_message():
    """Test ResultMessage serialization/deserialization."""
    model: TypeAdapter[MessageModel] = TypeAdapter(MessageModel)

    result_msg = ResultMessage(
        subtype="success",
        duration_ms=1000,
        duration_api_ms=800,
        is_error=False,
        num_turns=5,
        session_id="sess_123",
        total_cost_usd=0.05,
    )
    validated = ResultMessageModel.model_validate(asdict(result_msg))
    result_msg_json = validated.model_dump_json()
    deserialized = model.validate_json(result_msg_json)

    assert isinstance(deserialized, ResultMessageModel)
    assert deserialized.session_id == "sess_123"
    assert deserialized.num_turns == 5
    assert deserialized.total_cost_usd == 0.05


def test_stream_event():
    """Test StreamEvent serialization/deserialization."""
    model: TypeAdapter[MessageModel] = TypeAdapter(MessageModel)

    stream_event = StreamEvent(
        uuid="evt_123",
        session_id="sess_456",
        event={"type": "content_block_start"},
    )
    validated = StreamEventModel.model_validate(asdict(stream_event))
    stream_event_json = validated.model_dump_json()
    deserialized = model.validate_json(stream_event_json)

    assert isinstance(deserialized, StreamEventModel)
    assert deserialized.uuid == "evt_123"
    assert deserialized.session_id == "sess_456"


def test_round_trip():
    """Test full round-trip serialization."""
    model: TypeAdapter[MessageModel] = TypeAdapter(MessageModel)

    # Create a complex message
    original = AssistantMessage(
        content=[
            TextBlock(text="Let me help you"),
            ToolUseBlock(id="t1", name="bash", input={"command": "ls"}),
            ToolResultBlock(tool_use_id="t1", content="file1.txt file2.txt"),
            TextBlock(text="Done!"),
        ],
        model="claude-3-5-sonnet-20241022",
        parent_tool_use_id="parent_t1",
    )

    # Serialize
    validated = AssistantMessageModel.model_validate(asdict(original))
    serialized = validated.model_dump_json()

    # Deserialize
    deserialized = model.validate_json(serialized)

    # Verify
    assert isinstance(deserialized, AssistantMessageModel)
    assert len(deserialized.content) == 4
    assert deserialized.model == "claude-3-5-sonnet-20241022"
    assert deserialized.parent_tool_use_id == "parent_t1"
    assert isinstance(deserialized.content[0], TextBlockModel)
    assert isinstance(deserialized.content[1], ToolUseBlockModel)
    assert isinstance(deserialized.content[2], ToolResultBlockModel)
    assert isinstance(deserialized.content[3], TextBlockModel)
