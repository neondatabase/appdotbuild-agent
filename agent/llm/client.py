"""Simplified client creation for LLM providers."""

import os
from typing import Dict, Any
from anthropic import AsyncAnthropic, AsyncAnthropicBedrock

from llm.common import AsyncLLM
from llm.providers import PROVIDERS, get_model_mapping
from log import get_logger

logger = get_logger(__name__)


def create_client(
    backend: str, model_name: str, client_params: Dict[str, Any] | None = None
) -> AsyncLLM:
    """Create an LLM client for the specified backend and model.

    Args:
        backend: The backend provider name (e.g., 'anthropic', 'gemini', 'ollama')
        model_name: The model name to use
        client_params: Additional parameters to pass to the client constructor

    Returns:
        An AsyncLLM client instance

    Raises:
        ValueError: If backend is unknown or not available
    """
    if backend not in PROVIDERS:
        raise ValueError(f"Unknown backend: {backend}")

    config = PROVIDERS[backend]
    client_class = config["client"]
    client_params = client_params or {}

    # get the backend-specific model name
    mapped_model = get_model_mapping(model_name, backend)

    # create client based on backend type
    match backend:
        case "bedrock":
            base_client = AsyncAnthropicBedrock(**client_params)
            return client_class(base_client, default_model=mapped_model)

        case "anthropic":
            base_client = AsyncAnthropic(**client_params)
            return client_class(base_client, default_model=mapped_model)

        case "gemini":
            return client_class(model_name=mapped_model, **client_params)

        case "ollama":
            # use OLLAMA_HOST/OLLAMA_API_BASE env vars or default
            host = (
                os.getenv("OLLAMA_HOST")
                or os.getenv("OLLAMA_API_BASE")
                or client_params.get("host", "http://localhost:11434")
            )
            return client_class(host=host, model_name=mapped_model)

        case "lmstudio":
            # check if model_name contains host (e.g., lmstudio:http://localhost:1234)
            if ":" in model_name and model_name.startswith("lmstudio:"):
                _, host_part = model_name.split(":", 1)
                # if host_part looks like a URL, use it as base_url
                if (
                    host_part
                    and host_part.startswith("http://")
                    or host_part.startswith("https://")
                ):
                    base_url = host_part if "/v1" in host_part else f"{host_part}/v1"
                else:
                    # otherwise use default
                    base_url = client_params.get("base_url", "http://localhost:1234/v1")
            else:
                # use default
                base_url = client_params.get("base_url", "http://localhost:1234/v1")
            return client_class(base_url=base_url, model_name=mapped_model)

        case "openrouter":
            # openrouter requires an API key
            api_key = os.getenv("OPENROUTER_API_KEY") or client_params.get("api_key")
            if not api_key:
                raise ValueError(
                    "OpenRouter backend requires OPENROUTER_API_KEY environment variable"
                )

            return client_class(
                model_name=mapped_model,
                api_key=api_key,
            )

        case "openai":
            api_key = os.getenv("OPENAI_API_KEY") or client_params.get("api_key")
            if not api_key:
                raise ValueError(
                    "OpenAI backend requires OPENAI_API_KEY environment variable"
                )
            base_url = os.getenv("OPENAI_BASE_URL") or client_params.get("base_url")
            if base_url:
                return client_class(
                    model_name=mapped_model, api_key=api_key, base_url=base_url
                )
            return client_class(model_name=mapped_model, api_key=api_key)

        case _:
            raise ValueError(f"Unsupported backend: {backend}")
