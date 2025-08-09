import itertools
import os
import re
from typing import Literal, Dict
from llm.common import AsyncLLM, Message, TextRaw, ContentBlock
from llm.cached import CachedLLM, CacheMode
from llm.models_config import ModelCategory, get_model_for_category
from llm.providers import get_backend_for_model
from llm.client import create_client
from log import get_logger
from hashlib import md5

logger = get_logger(__name__)

# cache for LLM clients
llm_clients_cache: Dict[str, AsyncLLM] = {}

LLMBackend = Literal[
    "bedrock", "anthropic", "gemini", "ollama", "lmstudio", "openrouter", "openai"
]


def merge_text(content: list[ContentBlock]) -> list[ContentBlock]:
    merged = []
    for k, g in itertools.groupby(content, lambda x: isinstance(x, TextRaw)):
        if k and (text := "".join([x.text for x in g if isinstance(x, TextRaw)])) != "":
            merged.append(TextRaw(text))
        else:
            merged.extend(g)
    return merged


def extract_tag(source: str | None, tag: str):
    if source is None:
        return None
    pattern = re.compile(rf"<{tag}>(.*?)</{tag}>", re.DOTALL)
    match = pattern.search(source)
    if match:
        return match.group(1).strip()
    return None


async def loop_completion(
    m_client: AsyncLLM,
    messages: list[Message],
    system_prompt: str | None = None,
    **kwargs,
) -> Message:
    content: list[ContentBlock] = []
    while True:
        payload = (
            messages + [Message(role="assistant", content=content)]
            if content
            else messages
        )
        completion = await m_client.completion(
            messages=payload, system_prompt=system_prompt, **kwargs
        )
        content.extend(completion.content)
        if completion.stop_reason != "max_tokens":
            break
    return Message(role="assistant", content=merge_text(content))


def _cache_key_from_seq(backend: str, model_name: str, params: frozenset) -> str:
    """Generate a unique cache key for client configuration."""
    key_parts = [backend, model_name, str(sorted(params))]
    s = "/".join(key_parts)
    return md5(s.encode()).hexdigest()


def get_llm_client(
    backend: Literal["auto"] | LLMBackend = "auto",
    model_name: str | None = None,
    category: str | None = None,
    cache_mode: CacheMode = "auto",
    client_params: dict | None = None,
) -> AsyncLLM:
    """Get a configured LLM client.

    Creates a singleton LLM client based on the provided parameters.
    If a client with the same parameters already exists, it will be returned.

    Args:
        backend: LLM backend provider or "auto" for automatic detection
        model_name: Specific model name to use (overrides category)
        category: Model category ("best_coding", "universal", "ultra_fast", "vision")
        cache_mode: Cache mode, either "off", "record", or "replay"
        client_params: Additional parameters to pass to the client constructor

    Returns:
        An AsyncLLM instance
    """
    # determine model name from category if not provided
    if model_name is None:
        if category is None:
            category = ModelCategory.UNIVERSAL
        model_name = get_model_for_category(category)

    # determine backend if auto
    if backend == "auto":
        detected_backend = get_backend_for_model(model_name)
        backend = detected_backend  # type: ignore[assignment]
        logger.info(f"Auto-detected backend: {backend}")

    # prepare parameters for caching
    client_params = client_params or {}
    params_key = frozenset(client_params.items())
    cache_key = _cache_key_from_seq(backend, model_name, params_key)

    # return existing client if cached
    if cache_key in llm_clients_cache:
        logger.debug(f"Returning cached LLM client for {backend}/{model_name}")
        return llm_clients_cache[cache_key]

    # create new client
    logger.debug(f"Creating new LLM client for {backend}/{model_name}")
    client = create_client(backend, model_name, client_params)

    # wrap with caching if enabled
    if cache_mode != "off":
        current_dir = os.path.dirname(__file__)
        cache_path = os.path.join(current_dir, "caches", f"{cache_key}.json")
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        client = CachedLLM(
            client, cache_mode=cache_mode, cache_path=cache_path, max_cache_size=256
        )

    # store in cache and return
    llm_clients_cache[cache_key] = client
    logger.debug(f"Created and cached LLM client for {backend}/{model_name}")
    return client


def get_best_coding_llm_client(**kwargs) -> AsyncLLM:
    """Get LLM client optimized for best coding (slow, high quality)."""
    return get_llm_client(category=ModelCategory.BEST_CODING, **kwargs)


def get_universal_llm_client(**kwargs) -> AsyncLLM:
    """Get LLM client optimized for universal tasks (medium speed, FSM tools)."""
    return get_llm_client(category=ModelCategory.UNIVERSAL, **kwargs)


def get_ultra_fast_llm_client(**kwargs) -> AsyncLLM:
    """Get LLM client optimized for ultra fast tasks (commit names etc)."""
    return get_llm_client(category=ModelCategory.ULTRA_FAST, **kwargs)


def get_vision_llm_client(**kwargs) -> AsyncLLM:
    """Get LLM client optimized for vision and UI analysis tasks."""
    return get_llm_client(category=ModelCategory.VISION, **kwargs)
