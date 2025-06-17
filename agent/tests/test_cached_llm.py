import pytest
import tempfile
from llm.cached import CachedLLM, AsyncLLM
from llm.common import Message, TextRaw, Completion, Tool, AttachedFiles
from llm.utils import get_llm_client, merge_text
import uuid
import ujson as json
import os

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

@pytest.mark.skipif(os.getenv("GEMINI_API_KEY") is None, reason="GEMINI_API_KEY is not set")
async def test_cached_llm():
    with tempfile.NamedTemporaryFile(delete_on_close=False) as tmp_file:
        base_llm = StubLLM()
        record_llm = CachedLLM(
            client=base_llm,
            cache_mode="record",
            cache_path=tmp_file.name,
        )

        call_args = {
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



@pytest.mark.skipif(os.getenv("GEMINI_API_KEY") is None, reason="GEMINI_API_KEY is not set")
async def test_cached_lru():
    with tempfile.NamedTemporaryFile(delete_on_close=False) as tmp_file:
        base_llm = StubLLM()
        record_llm = CachedLLM(
            client=base_llm,
            cache_mode="lru",
            cache_path=tmp_file.name,
            max_cache_size=2,
        )

        requests = {
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

@pytest.mark.skipif(os.getenv("GEMINI_API_KEY") is None, reason="GEMINI_API_KEY is not set")
async def test_gemini():
    client = get_llm_client(model_name="gemini-flash")
    resp = await client.completion(
        messages=[Message(role="user", content=[TextRaw("Hello, what are you?")])],
        max_tokens=512,
    )
    text, = merge_text(resp.content)
    match text:
        case TextRaw(text=text):
            assert text != "", "Gemini should return a non-empty response"
        case _:
            raise ValueError(f"Unexpected content type: {type(text)}")


@pytest.mark.skipif(os.getenv("GEMINI_API_KEY") is None, reason="GEMINI_API_KEY is not set")
async def test_gemini_with_image():
    client = get_llm_client(model_name="gemini-flash-lite")
    image_path = os.path.join(
        os.path.dirname(__file__),
        "image.png",
    )
    resp = await client.completion(
        messages=[Message(role="user", content=[TextRaw("Answer only what is written in the image, single word")])],
        max_tokens=512,
        attach_files=AttachedFiles(files=[image_path], _cache_key="test")
    )
    text, = merge_text(resp.content)

    match text:
        case TextRaw(text=text):
            assert "app.build" in text.lower(), f"Gemini should return 'app.build', got {text}"
        case _:
            raise ValueError(f"Unexpected content type: {type(text)}")
