"""
OpenRouter client leveraging the generic OpenAI-format implementation.

This class is intentionally minimal: OpenRouter exposes an OpenAI-compatible
Chat Completions API, so we simply subclass the generic OpenAILLM adapter
and only customize:
  - provider name (for telemetry / logging)
  - default base URL
  - API key environment variable (OPENROUTER_API_KEY)

If you need advanced routing / provider ordering supported by OpenRouter,
you can extend this class further without duplicating the message / tool
transformation logic already implemented in `OpenAILLM`.
"""

from __future__ import annotations

import os
from typing import Any
from llm.openai_client import OpenAILLM
from log import get_logger

logger = get_logger(__name__)


class OpenRouterLLM(OpenAILLM):
    provider_name = "OpenRouter"

    def __init__(
        self,
        model_name: str = "openai/gpt-4o-mini",
        api_key: str | None = None,
        base_url: str = "https://openrouter.ai/api/v1",
        site_url: str | None = None,
        site_name: str | None = None,
        **kwargs: Any,
    ):
        """
        Args:
            model_name: Full model identifier as exposed by OpenRouter
            api_key: Explicit API key (else taken from OPENROUTER_API_KEY)
            base_url: Override base URL (defaults to official OpenRouter endpoint)
            site_url: (Optional) Attribution URL (currently logged only)
            site_name: (Optional) Attribution name (currently logged only)
            **kwargs: Forwarded to OpenAILLM (e.g. organization / project / base_url override)
        """
        key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise ValueError(
                "OpenRouter API key required. Set OPENROUTER_API_KEY environment variable."
            )

        # Log (but presently not injecting into headers since the base client
        # wrapper does not yet expose default_headers injection).
        if site_url or site_name:
            logger.info(
                f"OpenRouter attribution (site_url={site_url!r}, site_name={site_name!r})"
            )

        super().__init__(
            model_name=model_name,
            api_key=key,
            base_url=base_url,
            provider_name=self.provider_name,
            **kwargs,
        )


__all__ = ["OpenRouterLLM"]
