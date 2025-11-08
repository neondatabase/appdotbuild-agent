"""
Gonka.ai Chat Completions backend implementation.

Gonka.ai is a decentralized AI inference network with OpenAI-compatible API.
During the Grace Period (6 months), inference runs at zero cost.

Features:
- OpenAI-compatible API
- Decentralized GPU network
- Zero-cost inference during Grace Period
- Support for large models (e.g., Qwen3-235B)

API Documentation: https://gonka.ai/introduction/
Inference Nodes: http://node2.gonka.ai:8000/v1/epochs/current/participants

Environment Variables:
- GONKA_PRIVATE_KEY: Private key for Gonka.ai (required)
- GONKA_SOURCE_URL: Genesis/inference node URL (default: http://node2.gonka.ai:8000)
"""

from __future__ import annotations

import os
import asyncio
from typing import List, Dict, Any, Literal, cast
try:
    from gonka_openai import GonkaOpenAI  # Official Gonka SDK (note: module uses underscore)
    GONKA_SDK_AVAILABLE = True
except ImportError:
    from openai import AsyncOpenAI
    GONKA_SDK_AVAILABLE = False
from llm.openai_client import OpenAILLM
from llm import common
from log import get_logger

logger = get_logger(__name__)


class GonkaLLM(OpenAILLM):
    """
    Gonka.ai client using OpenAI-compatible API.

    Gonka.ai is a decentralized AI compute network providing
    zero-cost inference during the Grace Period.

    Usage:
        # Set environment variables
        export GONKA_PRIVATE_KEY="your-private-key"
        export GONKA_SOURCE_URL="http://node2.gonka.ai:8000"  # optional

        # Via model category configuration
        LLM_BEST_CODING_MODEL=gonka:Qwen/Qwen3-235B-A22B-Instruct-2507-FP8
        LLM_UNIVERSAL_MODEL=gonka:Qwen/Qwen3-235B-A22B-Instruct-2507-FP8
    """

    provider_name: str = "Gonka"

    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-235B-A22B-Instruct-2507-FP8",
        api_key: str | None = None,
        base_url: str | None = None,
        provider_name: str | None = None,
    ):
        """
        Initialize Gonka.ai client.

        Args:
            model_name: Model to use (default: Qwen/Qwen3-235B-A22B-Instruct-2507-FP8)
                       View nodes: http://node2.gonka.ai:8000/v1/epochs/current/participants
            api_key: Gonka private key (or set GONKA_PRIVATE_KEY env var)
            base_url: Source URL - genesis/inference node (default: http://node2.gonka.ai:8000)
            provider_name: Override provider name for logging
        """
        # Get Gonka-specific config
        gonka_private_key = api_key or os.getenv("GONKA_PRIVATE_KEY") or os.getenv("GONKA_API_KEY")
        gonka_source_url = base_url or os.getenv("GONKA_SOURCE_URL") or os.getenv("GONKA_BASE_URL") or "http://node2.gonka.ai:8000"

        if not gonka_private_key:
            raise ValueError(
                "Gonka.ai private key required. Set GONKA_PRIVATE_KEY environment variable or pass api_key parameter."
            )

        #  Store source_url
        self.source_url = gonka_source_url

        # Use official Gonka SDK if available
        if GONKA_SDK_AVAILABLE:
            # Create GonkaOpenAI client
            self.client = GonkaOpenAI(
                gonka_private_key=gonka_private_key,
                source_url=gonka_source_url,
            )
            self.model_name = model_name
            self.default_model = model_name
            self.api_key = gonka_private_key
            if provider_name:
                self.provider_name = provider_name
        else:
            # Fallback to standard OpenAI client (will need manual source_url injection)
            base_url_with_v1 = gonka_source_url if gonka_source_url.endswith("/v1") else f"{gonka_source_url}/v1"
            super().__init__(
                model_name=model_name,
                api_key=gonka_private_key,
                base_url=base_url_with_v1,
                provider_name=provider_name or self.provider_name,
            )

    async def completion(
        self,
        messages: List[common.Message],
        max_tokens: int,
        model: str | None = None,
        temperature: float = 1.0,
        tools: List[common.Tool] | None = None,
        tool_choice: str | None = None,
        system_prompt: str | None = None,
        *args,
        **kwargs,
    ) -> common.Completion:
        """Override completion to handle Gonka SDK or inject source_url.

        If official Gonka SDK is available, it handles source_url automatically.
        Otherwise, inject source_url manually for standard OpenAI client.
        """
        if not GONKA_SDK_AVAILABLE:
            # Fallback: inject source_url via extra_body for standard OpenAI client
            original_create = self.client.chat.completions.create

            async def create_with_source_url(**request_kwargs):
                """Wrapper to inject source_url via extra_body."""
                if "extra_body" not in request_kwargs:
                    request_kwargs["extra_body"] = {}
                request_kwargs["extra_body"]["source_url"] = self.source_url
                return await original_create(**request_kwargs)

            self.client.chat.completions.create = create_with_source_url
            try:
                return await super().completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    model=model,
                    temperature=temperature,
                    tools=tools,
                    tool_choice=tool_choice,
                    system_prompt=system_prompt,
                    *args,
                    **kwargs,
                )
            finally:
                self.client.chat.completions.create = original_create
        else:
            # Use official Gonka SDK - it's synchronous, so wrap in thread
            # The Gonka SDK doesn't support async, so we need to call it sync
            logger.info(f"Using Gonka SDK (sync) for model {model or self.default_model}")

            # Build messages in OpenAI format
            openai_messages = self._messages_into(messages)
            if system_prompt:
                openai_messages.insert(0, {"role": "system", "content": system_prompt})

            # Build request
            request: Dict[str, Any] = {
                "model": model or self.default_model,
                "messages": openai_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            # Add tools if provided
            openai_tools = self._tools_into(tools)
            if openai_tools:
                request["tools"] = openai_tools
                if tool_choice:
                    request["tool_choice"] = {
                        "type": "function",
                        "function": {"name": tool_choice},
                    }

            # Call synchronous Gonka SDK in thread pool
            def sync_create():
                return self.client.chat.completions.create(**request)

            response = await asyncio.to_thread(sync_create)

            # Convert response to our format
            return self._completion_into(response)


__all__ = ["GonkaLLM"]
