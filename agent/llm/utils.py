import itertools
import os
from typing import Literal, Dict, Sequence
from anthropic import AsyncAnthropic, AsyncAnthropicBedrock
from llm.common import AsyncLLM, Message, TextRaw, ContentBlock
from llm.anthropic_client import AnthropicLLM
from llm.cached import CachedLLM, CacheMode
from llm.gemini import GeminiLLM
from log import get_logger
from hashlib import md5

logger = get_logger(__name__)

# Cache for LLM clients
llm_clients_cache: Dict[str, AsyncLLM] = {}

LLMBackend = Literal["bedrock", "anthropic", "gemini"]


def merge_text(content: list[ContentBlock]) -> list[ContentBlock]:
    merged = []
    for k, g in itertools.groupby(content, lambda x: isinstance(x, TextRaw)):
        if k and (text := "".join([x.text for x in g if isinstance(x, TextRaw)])) != "":
            merged.append(TextRaw(text))
        else:
            merged.extend(g)
    return merged


async def loop_completion(m_client: AsyncLLM, messages: list[Message], system_prompt: str | None = None, **kwargs) -> Message:
    content: list[ContentBlock] = []
    while True:
        payload = messages + [Message(role="assistant", content=content)] if content else messages
        completion = await m_client.completion(messages=payload, system_prompt=system_prompt, **kwargs)
        content.extend(completion.content)
        if completion.stop_reason != "max_tokens":
            break
    return Message(role="assistant", content=merge_text(content))


def _guess_llm_backend(model_name: str) -> LLMBackend:
    match model_name:
        case ("sonnet" | "haiku"):
            if os.getenv("AWS_SECRET_ACCESS_KEY") or os.getenv("PREFER_BEDROCK"):
                return "bedrock"
            if os.getenv("ANTHROPIC_API_KEY"):
                return "anthropic"
            # that is rare case, but may be non-trivial AWS config, try Bedrock again
            return "bedrock"
        case ("gemini-flash" | "gemini-pro" | "gemini-flash-lite"):
            if os.getenv("GEMINI_API_KEY"):
                return "gemini"
            raise ValueError("Gemini backend requires GEMINI_API_KEY to be set")
        case _:
            raise ValueError(f"Unknown model name: {model_name}")


def _cache_key_from_seq(key: Sequence) -> str:
    s = "/".join(map(str, key))
    return md5(s.encode()).hexdigest()


def get_llm_client(
    backend: Literal["auto"] | LLMBackend = "auto",
    model_name: Literal["sonnet", "haiku", "gemini-flash", "gemini-pro", "gemini-flash-lite"] = "sonnet",
    cache_mode: CacheMode = "auto",
    client_params: dict | None = None,
) -> AsyncLLM:
    """Get a configured LLM client for the fullstack application.

    Creates a singleton LLM client based on the provided parameters.
    If a client with the same parameters already exists, it will be returned.

    Args:
        backend: LLM backend provider, either "bedrock" or "anthropic"
        model_name: Model name to use, either "sonnet" or "haiku"
        cache_mode: Cache mode, either "off", "record", or "replay"
        cache_path: Path to the cache file
        client_params: Additional parameters to pass to the client constructor

    Returns:
        An AsyncLLM instance
    """
    # Convert client_params dict to frozenset for caching
    client_params = client_params or {}
    params_key = frozenset(client_params.items())

    if backend == "auto":
        backend = _guess_llm_backend(model_name)
        logger.info(f"Auto-detected backend: {backend}")

    cache_key = _cache_key_from_seq((model_name, params_key))

    # Return existing client if one exists with the same configuration
    if cache_key in llm_clients_cache:
        logger.debug(f"Returning existing LLM client for {backend}/{model_name}")
        return llm_clients_cache[cache_key]

    # Otherwise create a new client
    models_map = {
        "sonnet": {
            "bedrock": "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "anthropic": "claude-sonnet-4-20250514"
        },
        "haiku": {
            "bedrock": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
            "anthropic": "claude-3-5-haiku-20241022"
        },
        "gemini-pro":
            {
                "gemini": "gemini-2.5-pro-preview-05-06",
            },
        "gemini-flash":
            {
                "gemini": "gemini-2.5-flash-preview-05-20",
            },
        "gemini-flash-lite":
            {
                "gemini": "gemini-2.5-flash-lite-preview-06-17",
            },
    }

    chosen_model = models_map[model_name][backend]

    match backend:
        case "bedrock" | "anthropic":
            base_client = AsyncAnthropicBedrock(**client_params) if backend == "bedrock" else AsyncAnthropic(**client_params)
            client = AnthropicLLM(base_client, default_model=chosen_model)
        case "gemini":
            client_params["model_name"] = chosen_model
            client = GeminiLLM(**client_params)
        case _:
            raise ValueError(f"Unknown backend: {backend}")

    if cache_mode != "off":
        current_dir = os.path.dirname(__file__)
        cache_path = os.path.join(current_dir, "caches", f"{cache_key}.json")
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        client = CachedLLM(client, cache_mode=cache_mode, cache_path=cache_path, max_cache_size=256)

    # Store the client in the cache
    llm_clients_cache[cache_key] = client
    logger.debug(f"Created new LLM client for {backend}/{model_name}")
    return client
