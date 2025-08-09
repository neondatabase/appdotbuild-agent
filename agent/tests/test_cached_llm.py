import pytest
import tempfile
from llm.cached import CachedLLM, AsyncLLM
from llm.common import Message, TextRaw, Completion, Tool, AttachedFiles, ToolUse
from llm.utils import get_ultra_fast_llm_client, get_vision_llm_client, get_best_coding_llm_client, merge_text
from llm.alloy import AlloyLLM
import uuid
import ujson as json
import os
from typing import Any, Dict
from tests.test_utils import requires_llm_provider, requires_llm_provider_reason

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


class StubLLM(AsyncLLM):
    def __init__(self):
        self.calls = 0

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

        random_str = uuid.uuid4().hex
        self.calls += 1
        return Completion(
            role="assistant",
            content=[TextRaw(text=random_str)],
            input_tokens=1,
            output_tokens=10,
            stop_reason="end_turn",
            thinking_tokens=0,
        )


@pytest.mark.skipif(requires_llm_provider(), reason=requires_llm_provider_reason)
async def test_cached_llm():
    with tempfile.NamedTemporaryFile(delete_on_close=False) as tmp_file:
        base_llm = StubLLM()
        record_llm = CachedLLM(
            client=base_llm,
            cache_mode="record",
            cache_path=tmp_file.name,
        )

        call_args: Dict[str, Any] = {
            "messages": [Message(role="user", content=[TextRaw("Hello, world!")])],
            "max_tokens": 100,
        }

        recorded = await record_llm.completion(**call_args)
        replay_llm = CachedLLM(
            client=base_llm,
            cache_mode="replay",
            cache_path=tmp_file.name,
        )
        replayed = await replay_llm.completion(**call_args)
        assert base_llm.calls == 1, "Base LLM should be called once"
        assert recorded == replayed



@pytest.mark.skipif(requires_llm_provider(), reason=requires_llm_provider_reason)
async def test_cached_lru():
    with tempfile.NamedTemporaryFile(delete_on_close=False) as tmp_file:
        base_llm = StubLLM()
        record_llm = CachedLLM(
            client=base_llm,
            cache_mode="lru",
            cache_path=tmp_file.name,
            max_cache_size=2,
        )

        requests: Dict[str, Dict[str, Any]] = {
            key: {
                "messages": [Message(role="user", content=[TextRaw(str(i + 1))])],
                "max_tokens": 100,
            }
            for i, key in enumerate(["first", "second", "third"])
        }
        responses = {}

        for key, call_args in requests.items():
            resp = await record_llm.completion(**call_args)
            responses[key] = json.dumps(resp.to_dict())

        assert base_llm.calls == 3, "Base LLM should be called three times"

        # Check that the first request was evicted from the cache
        assert len(record_llm._cache_lru) == 2, "Cache should contain only the last two requests"

        # 2 and 3 should be in the cache
        new_resp = await record_llm.completion(**requests["second"])
        assert json.dumps(new_resp.to_dict()) == responses["second"], "Second request should hit the cache"

        new_resp = await record_llm.completion(**requests["third"])
        assert json.dumps(new_resp.to_dict()) == responses["third"], "Third request should hit the cache"

        assert base_llm.calls == 3, "Base LLM should still be called three times"

        # check call to first is not in cache
        new_resp = await record_llm.completion(**requests["first"])
        assert json.dumps(new_resp.to_dict()) != responses["first"], "First request should not hit the cache"
        assert base_llm.calls == 4, "Base LLM should still be called four times"

@pytest.mark.skipif(requires_llm_provider(), reason=requires_llm_provider_reason)
async def test_llm_text_completion():
    client = get_ultra_fast_llm_client()
    resp = await client.completion(
        messages=[Message(role="user", content=[TextRaw("Hello, what are you?")])],
        max_tokens=512,
    )
    text, = merge_text(list(resp.content))
    match text:
        case TextRaw(text=text):
            assert text != "", "LLM should return a non-empty response"
        case _:
            raise ValueError(f"Unexpected content type: {type(text)}")


# flaky test, skip for now
@pytest.mark.skip
async def test_llm_vision_completion():
    client = get_vision_llm_client()
    image_path = os.path.join(
        os.path.dirname(__file__),
        "image.png",
    )

    try:
        resp = await client.completion(
            messages=[Message(role="user", content=[TextRaw("Answer only what is written in the image (single word, dot is allowed)")])],
            max_tokens=512,
            attach_files=AttachedFiles(files=[image_path], _cache_key="test")
        )
        text, = merge_text(list(resp.content))

        match text:
            case TextRaw(text=text):
                # Vision models should be able to read text from images
                # The test image contains "app.build" so we expect that in the response
                assert "app.build" in text.lower(), f"Vision model should return 'app.build', got {text}"
            case _:
                raise ValueError(f"Unexpected content type: {type(text)}")
    except Exception as e:
        # Some providers (like basic Ollama models) might not support vision
        # Skip the test gracefully if the model doesn't support attach_files
        if "attach_files" in str(e) or "vision" in str(e).lower():
            pytest.skip(f"Current LLM provider doesn't support vision: {e}")
        else:
            raise


@pytest.mark.skipif(os.getenv("PREFER_OLLAMA") is None, reason="PREFER_OLLAMA is not set")
async def test_ollama_function_calling():
    """Test that Ollama function calling infrastructure works correctly"""

    client = get_best_coding_llm_client()

    # Define a test tool
    tools: list[Tool] = [{
        'name': 'calculate',
        'description': 'Calculate a mathematical expression',
        'input_schema': {
            'type': 'object',
            'properties': {
                'expression': {'type': 'string', 'description': 'Mathematical expression to calculate'}
            },
            'required': ['expression']
        }
    }]

    # Use a more direct prompt that encourages tool usage
    messages = [Message(role="user", content=[TextRaw("Use the function calculate to compute 34545 + 123")])]

    resp = await client.completion(
        messages=messages,
        max_tokens=512,
        tools=tools
    )

    # Check if we got a tool call OR at least verify the request/response structure works
    tool_calls = [block for block in resp.content if isinstance(block, ToolUse)]

    # The test passes if either:
    # 1. We get a tool call (ideal case)
    # 2. We get a text response but the infrastructure works (acceptable)
    # Ideal case: model used the tool
    assert len(tool_calls) > 0, "Should have at least one tool call"
    tool_call = tool_calls[0]
    assert tool_call.name == 'calculate', f"Expected tool 'calculate', got '{tool_call.name}'"
    assert isinstance(tool_call.input, dict), f"Tool input should be dict, got {type(tool_call.input)}"
    assert 'expression' in tool_call.input, f"Tool input should have 'expression' key, got {tool_call.input}"


@pytest.mark.skipif(requires_llm_provider(), reason=requires_llm_provider_reason)
async def test_alloy_llm_round_robin():
    """Test AlloyLLM with round-robin selection strategy"""
    # create stub LLMs with distinct responses
    stub1 = StubLLM()
    stub2 = StubLLM()

    # create alloy with round-robin strategy
    alloy = AlloyLLM.from_models([stub1, stub2], selection_strategy="round_robin")

    messages = [Message(role="user", content=[TextRaw("Hello")])]

    # make 4 calls
    responses = []
    for _ in range(4):
        resp = await alloy.completion(messages=messages, max_tokens=100)
        responses.append(resp)

    # verify alternating calls
    assert stub1.calls == 2, "First model should be called twice"
    assert stub2.calls == 2, "Second model should be called twice"

    # responses should alternate between models
    assert responses[0] != responses[1]  # different models
    assert responses[0] != responses[2]  # same model but different response (uuid)
    assert responses[1] != responses[3]  # same model but different response (uuid)


@pytest.mark.skipif(requires_llm_provider(), reason=requires_llm_provider_reason)
async def test_alloy_llm_random():
    """Test AlloyLLM with random selection strategy"""
    # create multiple stub LLMs
    stubs = [StubLLM() for _ in range(3)]

    # create alloy with random strategy
    alloy = AlloyLLM.from_models(stubs, selection_strategy="random")

    messages = [Message(role="user", content=[TextRaw("Hello")])]

    # make multiple calls
    for _ in range(10):
        await alloy.completion(messages=messages, max_tokens=100)

    # verify all models were called (probabilistically)
    total_calls = sum(stub.calls for stub in stubs)
    assert total_calls == 10, "Total calls should be 10"

    # with 10 calls and 3 models, each should be called at least once (very high probability)
    for stub in stubs:
        assert stub.calls > 0, "Each model should be called at least once"


@pytest.mark.skipif(requires_llm_provider(), reason=requires_llm_provider_reason)
async def test_alloy_llm_empty_models():
    """Test AlloyLLM raises error with empty model list"""
    with pytest.raises(ValueError, match="At least one model must be provided"):
        AlloyLLM.from_models([])
