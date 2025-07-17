import itertools
import os
import re
from typing import Literal, Dict, Sequence
from anthropic import AsyncAnthropic, AsyncAnthropicBedrock
from llm.common import AsyncLLM, Message, TextRaw, ContentBlock
from llm.anthropic_client import AnthropicLLM
from llm.cached import CachedLLM, CacheMode
from llm.gemini import GeminiLLM
from llm.models_config import MODELS_MAP, ALL_MODEL_NAMES, OLLAMA_MODEL_NAMES, ANTHROPIC_MODEL_NAMES, GEMINI_MODEL_NAMES, ModelCategory, get_model_for_category

from log import get_logger
from hashlib import md5

try:
    from llm.ollama_client import OllamaLLM
except ImportError:
    OllamaLLM = None

logger = get_logger(__name__)

# Cache for LLM clients
llm_clients_cache: Dict[str, AsyncLLM] = {}

LLMBackend = Literal["bedrock", "anthropic", "gemini", "ollama"]


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
    # If PREFER_OLLAMA is set and model is available in Ollama, use Ollama
    if os.getenv("PREFER_OLLAMA") and model_name in OLLAMA_MODEL_NAMES:
        return "ollama"
    
    if model_name in ANTHROPIC_MODEL_NAMES:
        if os.getenv("AWS_SECRET_ACCESS_KEY") or os.getenv("PREFER_BEDROCK"):
            return "bedrock"
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic"
        # that is rare case, but may be non-trivial AWS config, try Bedrock again
        return "bedrock"
    elif model_name in GEMINI_MODEL_NAMES:
        if os.getenv("GEMINI_API_KEY"):
            return "gemini"
        raise ValueError("Gemini backend requires GEMINI_API_KEY to be set")
    elif model_name in OLLAMA_MODEL_NAMES:
        # Default to localhost if no host is specified
        return "ollama"
    else:
        # Check if PREFER_OLLAMA is set or OLLAMA_HOST is configured
        # This allows using any Ollama model not in the predefined list
        if os.getenv("PREFER_OLLAMA") or os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_API_BASE"):
            logger.info(f"Using Ollama backend for custom model: {model_name}")
            return "ollama"
        raise ValueError(f"Unknown model name: {model_name}")


def _cache_key_from_seq(key: Sequence) -> str:
    s = "/".join(map(str, key))
    return md5(s.encode()).hexdigest()


def get_llm_client(
    backend: Literal["auto"] | LLMBackend = "auto",
    model_name: str | None = None,
    category: str | None = None,
    cache_mode: CacheMode = "auto",
    client_params: dict | None = None,
) -> AsyncLLM:
    """Get a configured LLM client for the fullstack application.

    Creates a singleton LLM client based on the provided parameters.
    If a client with the same parameters already exists, it will be returned.

    Args:
        backend: LLM backend provider, either "bedrock", "anthropic", "gemini", or "ollama"
        model_name: Specific model name to use (overrides category)
        category: Model category ("best_coding", "universal", "ultra_fast", "vision") for automatic selection
        cache_mode: Cache mode, either "off", "record", or "replay"
        client_params: Additional parameters to pass to the client constructor

    Returns:
        An AsyncLLM instance
    """
    if model_name is None:
        if category is None:
            category = ModelCategory.UNIVERSAL
        model_name = get_model_for_category(category)
    
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
    if model_name not in MODELS_MAP:
        # Allow any model for Ollama backend
        if backend == "ollama":
            logger.info(f"Using custom Ollama model: {model_name}")
            chosen_model = model_name
        else:
            raise ValueError(f"Unknown model name: {model_name}. Available models: {', '.join(ALL_MODEL_NAMES)}")
    else:
        chosen_model = MODELS_MAP[model_name][backend]

    match backend:
        case "bedrock" | "anthropic":
            base_client = AsyncAnthropicBedrock(**client_params) if backend == "bedrock" else AsyncAnthropic(**client_params)
            client = AnthropicLLM(base_client, default_model=chosen_model)
        case "gemini":
            client_params["model_name"] = chosen_model
            client = GeminiLLM(**client_params)
        case "ollama":
            if OllamaLLM is None:
                raise ValueError("Ollama backend requires ollama package to be installed. Install with: uv sync --group ollama")
            # Use OLLAMA_HOST/OLLAMA_API_BASE env vars or default to localhost
            host = (
                os.getenv("OLLAMA_HOST") or 
                os.getenv("OLLAMA_API_BASE") or 
                client_params.get("host", "http://localhost:11434")
            )
            client = OllamaLLM(host=host, model_name=chosen_model)
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
