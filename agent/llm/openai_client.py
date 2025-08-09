"""
OpenAI Chat Completions backend implementation.

Bridges internal (common.py) message / tool abstractions to any OpenAI
Chat Completions API compatible endpoint (OpenAI, local proxies like
LMStudio, OpenRouter style endpoints, etc.)

Supports:
- Tool / function calling
- System prompts
- Token usage telemetry
- Retry for transient errors
- Provider name override for subclasses / alternative endpoints
"""

from __future__ import annotations

from typing import List, Dict, Any, Literal, cast
from openai import AsyncOpenAI
import json
import os
import logging
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    before_sleep_log,
)
from llm import common
from llm.common import ToolUseResult
from llm.telemetry import LLMTelemetry
from log import get_logger

logger = get_logger(__name__)


class OpenAILLM:
    """
    Thin wrapper around a Chat Completions API adapting it to the
    internal AsyncLLM protocol (see llm.common.AsyncLLM).

    Subclasses (or alternative providers reusing OpenAI format) can
    override:
      - class attribute `provider_name`
      - or pass provider_name parameter at init
    """

    provider_name: str = "OpenAI"  # override in subclasses if needed

    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        api_key: str | None = None,
        base_url: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        provider_name: str | None = None,
    ):
        # allow runtime override
        if provider_name:
            self.provider_name = provider_name

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                f"{self.provider_name} API key required. Set OPENAI_API_KEY environment variable."
            )

        # Allow custom base_url (Azure, proxy, etc.)
        client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        if organization:
            client_kwargs["organization"] = organization
        if project:
            client_kwargs["project"] = project

        self.client = AsyncOpenAI(**client_kwargs)
        self.model_name = model_name
        self.default_model = model_name

        logger.info(
            f"Initialized {self.provider_name} client model={model_name} "
            f"{'(custom base_url)' if base_url else ''}"
        )

    # ------------- Internal transforms -------------

    def _messages_into(self, messages: List[common.Message]) -> List[Dict[str, Any]]:
        """
        Convert internal messages to OpenAI-format chat messages.

        Tool results become separate messages with role='tool'.
        """
        openai_messages: List[Dict[str, Any]] = []

        for message in messages:
            content_parts: List[Dict[str, Any]] = []
            tool_calls: List[Dict[str, Any]] = []
            tool_results: List[common.ToolResult] = []

            for block in message.content:
                if isinstance(block, common.TextRaw):
                    content_parts.append({"type": "text", "text": block.text})
                elif isinstance(block, common.ToolUse):
                    arguments = block.input
                    if not isinstance(arguments, str):
                        try:
                            arguments = json.dumps(arguments)
                        except (TypeError, ValueError):
                            arguments = str(arguments)
                    tool_calls.append(
                        {
                            "id": block.id,
                            "type": "function",
                            "function": {
                                "name": block.name,
                                "arguments": arguments,
                            },
                        }
                    )
                elif isinstance(block, ToolUseResult):
                    # Extract the tool_result with proper tool_use_id from ToolUseResult
                    tool_results.append(block.tool_result)
                elif isinstance(block, common.ToolResult):
                    tool_results.append(block)

            if tool_results:
                if content_parts or tool_calls:
                    openai_msg: Dict[str, Any] = {"role": message.role}
                    if content_parts:
                        if (
                            len(content_parts) == 1
                            and content_parts[0]["type"] == "text"
                        ):
                            openai_msg["content"] = content_parts[0]["text"]
                        else:
                            openai_msg["content"] = content_parts  # type: ignore
                    elif message.role == "user":
                        openai_msg["content"] = ""
                    if tool_calls:
                        openai_msg["tool_calls"] = tool_calls  # type: ignore
                    openai_messages.append(openai_msg)

                for tr in tool_results:
                    if not tr.tool_use_id:
                        # This is a critical error for OpenAI API - it requires tool_call_id
                        raise ValueError(
                            f"ToolResult missing required tool_use_id. "
                            f"Content: {tr.content[:100]}... "
                            f"This is required for OpenAI API compatibility."
                        )
                    openai_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tr.tool_use_id,
                            "content": tr.content,
                        }
                    )
            else:
                if content_parts or tool_calls or message.role == "user":
                    openai_msg: Dict[str, Any] = {"role": message.role}
                    if content_parts:
                        if (
                            len(content_parts) == 1
                            and content_parts[0]["type"] == "text"
                        ):
                            openai_msg["content"] = content_parts[0]["text"]
                        else:
                            openai_msg["content"] = content_parts  # type: ignore
                    elif not tool_calls and message.role == "user":
                        openai_msg["content"] = ""
                    if tool_calls:
                        openai_msg["tool_calls"] = tool_calls  # type: ignore
                    openai_messages.append(openai_msg)

        return openai_messages

    def _tools_into(
        self, tools: List[common.Tool] | None
    ) -> List[Dict[str, Any]] | None:
        if not tools:
            return None

        result: List[Dict[str, Any]] = []
        for tool in tools:
            name = tool.get("name")
            if not name:
                logger.warning(f"Skipping tool missing name: {tool}")
                continue
            description = tool.get("description", "")
            parameters = tool.get("input_schema", {})

            if parameters and not isinstance(parameters, dict):
                logger.warning(
                    f"Tool {name} input_schema invalid (not dict) - using empty schema"
                )
                parameters = {}

            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )

        return result or None

    def _completion_into(self, response: Any) -> common.Completion:
        """
        Convert OpenAI-format response to internal Completion.
        """
        content_blocks: List[common.TextRaw | common.ToolUse] = []

        choice = response.choices[0]
        message = choice.message

        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    if isinstance(tc.function.arguments, str):
                        args = json.loads(tc.function.arguments)
                    else:
                        args = tc.function.arguments
                except Exception:
                    args = tc.function.arguments
                content_blocks.append(
                    common.ToolUse(
                        name=tc.function.name,
                        input=args,
                        id=tc.id,
                    )
                )
            if message.content:
                content_blocks.append(common.TextRaw(message.content))
        else:
            if message.content:
                content_blocks.append(common.TextRaw(message.content))

        finish_reason = choice.finish_reason
        stop_reason_map = {
            "stop": "end_turn",
            "length": "max_tokens",
            "tool_calls": "tool_use",
            "content_filter": "stop_sequence",
            None: "unknown",
        }
        stop_reason = cast(
            Literal["end_turn", "max_tokens", "stop_sequence", "tool_use", "unknown"],
            stop_reason_map.get(finish_reason, "unknown"),
        )

        usage = getattr(response, "usage", None)
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        return common.Completion(
            role="assistant",
            content=content_blocks,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=stop_reason,
        )

    # ------------- Public API -------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=40, jitter=1),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
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
        chosen_model = model or self.default_model
        openai_messages = self._messages_into(messages)

        if system_prompt:
            openai_messages.insert(0, {"role": "system", "content": system_prompt})

        # Use appropriate max tokens parameter based on model
        # Newer models (gpt-4-turbo-2024-04-09 and later, including o1 models) use max_completion_tokens
        # Older models use max_tokens
        use_completion_tokens = any(
            prefix in chosen_model.lower()
            for prefix in ["gpt-4-turbo-2024", "gpt-4o", "o1-", "gpt-5"]
        )

        request: Dict[str, Any] = {
            "model": chosen_model,
            "messages": openai_messages,
            "temperature": temperature,
        }

        if use_completion_tokens:
            request["max_completion_tokens"] = max_tokens
        else:
            request["max_tokens"] = max_tokens

        openai_tools = self._tools_into(tools)
        if openai_tools:
            request["tools"] = openai_tools
            if tool_choice:
                request["tool_choice"] = {
                    "type": "function",
                    "function": {"name": tool_choice},
                }

        logger.info(
            f"{self.provider_name} request model={chosen_model} temp={temperature} max_tokens={max_tokens} "
            f"tools={len(openai_tools) if openai_tools else 0} "
            f"{'tool_choice=' + tool_choice if tool_choice else ''}"
        )

        telemetry = LLMTelemetry()
        telemetry.start_timing()

        try:
            response = await self.client.chat.completions.create(**request)
        except Exception as e:
            logger.error(
                f"{self.provider_name} API error for model '{chosen_model}': {e}"
            )
            raise

        if hasattr(response, "usage") and response.usage:
            telemetry.log_completion(
                model=chosen_model,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                temperature=temperature,
                has_tools=openai_tools is not None,
                provider=self.provider_name,
            )

        completion = self._completion_into(response)

        tool_use_blocks = [
            b for b in completion.content if isinstance(b, common.ToolUse)
        ]
        if tool_use_blocks:
            logger.info(
                f"{self.provider_name} response tool_calls={len(tool_use_blocks)} "
                f"names={[b.name for b in tool_use_blocks]}"
            )

        logger.info(
            f"{self.provider_name} response stop_reason={completion.stop_reason} "
            f"input={completion.input_tokens} output={completion.output_tokens}"
        )
        return completion


__all__ = ["OpenAILLM"]
