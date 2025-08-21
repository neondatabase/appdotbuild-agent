from typing import List, Dict, Any
import ollama
from llm import common
from llm.telemetry import LLMTelemetry
from log import get_logger
import logging
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    before_sleep_log,
)

logger = get_logger(__name__)


class OllamaLLM:
    def __init__(
        self, host: str = "http://localhost:11434", model_name: str = "devstral:latest"
    ):
        self.client = ollama.AsyncClient(host=host)
        self.model_name = model_name
        self.default_model = model_name

    def _messages_into(self, messages: List[common.Message]) -> List[Dict[str, Any]]:
        ollama_messages = []
        for message in messages:
            content_parts = []
            tool_calls = []

            for block in message.content:
                if isinstance(block, common.TextRaw):
                    content_parts.append(block.text)
                elif isinstance(block, common.ToolUse):
                    tool_calls.append(
                        {
                            "type": "function",
                            "function": {"name": block.name, "arguments": block.input},
                        }
                    )
                elif isinstance(block, common.ToolResult):
                    content_parts.append(f"Tool result: {block.content}")

            ollama_message: Dict[str, Any] = {
                "role": message.role,
                "content": " ".join(content_parts) if content_parts else "",
            }

            if tool_calls:
                ollama_message["tool_calls"] = tool_calls

            ollama_messages.append(ollama_message)

        return ollama_messages

    def _tools_into(
        self, tools: List[common.Tool] | None
    ) -> List[Dict[str, Any]] | None:
        if not tools:
            return None

        return [
            {
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                },
            }
            for tool in tools
        ]

    def _completion_into(
        self, response: Dict[str, Any], input_tokens: int = 0
    ) -> common.Completion:
        content_blocks = []

        message = response.get("message", {})
        content = message.get("content", "")

        if content:
            content_blocks.append(common.TextRaw(content))

        tool_calls = message.get("tool_calls", [])
        for tool_call in tool_calls:
            # ollama returns dict format: {"id": "...", "type": "function", "function": {"name": "...", "arguments": {...}}}
            if isinstance(tool_call, dict) and "function" in tool_call:
                func = tool_call["function"]
                content_blocks.append(
                    common.ToolUse(
                        name=func.get("name", ""),
                        input=func.get("arguments", {}),
                        id=tool_call.get("id", ""),
                    )
                )
            # fallback for object format (if ollama client changes)
            elif hasattr(tool_call, "function"):
                func = tool_call.function
                content_blocks.append(
                    common.ToolUse(
                        name=getattr(func, "name", ""),
                        input=getattr(func, "arguments", {}),
                        id=getattr(tool_call, "id", ""),
                    )
                )

        output_tokens = response.get("eval_count", 0)
        prompt_tokens = response.get("prompt_eval_count", input_tokens)

        return common.Completion(
            role="assistant",
            content=content_blocks,
            input_tokens=prompt_tokens,
            output_tokens=output_tokens,
            stop_reason="end_turn",
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=60, jitter=1),
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
        ollama_messages = self._messages_into(messages)

        if system_prompt:
            ollama_messages.insert(0, {"role": "system", "content": system_prompt})

        request_params = {
            "model": chosen_model,
            "messages": ollama_messages,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        ollama_tools = self._tools_into(tools)
        if ollama_tools:
            request_params["tools"] = ollama_tools

        logger.info(f"Ollama request params: {request_params}")
        telemetry = LLMTelemetry()
        telemetry.start_timing()

        response = await self.client.chat(**request_params)

        # log telemetry - ollama returns token counts in response dict
        # use None instead of 0 as default to trigger validation if tokens are missing
        input_tokens = response.get("prompt_eval_count")
        output_tokens = response.get("eval_count")

        telemetry.log_completion(
            model=chosen_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            temperature=temperature,
            has_tools=ollama_tools is not None,
            provider="Ollama",
        )

        logger.info(f"Ollama raw response: {response}")
        completion = self._completion_into(response, input_tokens=input_tokens)
        logger.info(
            f"Parsed completion: content_length={len(completion.content)}, stop_reason={completion.stop_reason}"
        )
        return completion
