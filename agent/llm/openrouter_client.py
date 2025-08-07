from typing import List, Dict, Any, Literal, cast
from openai import AsyncOpenAI
import json
import os
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


class OpenRouterLLM:
    def __init__(
        self,
        base_url: str = "https://openrouter.ai/api/v1",
        model_name: str = "openai/gpt-4o-mini",
        api_key: str | None = None,
        site_url: str | None = None,
        site_name: str | None = None,
    ):
        # use provided API key or get from environment
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenRouter API key required. Set OPENROUTER_API_KEY environment variable."
            )

        # configure headers for app attribution if provided
        headers = {}
        if site_url:
            headers["HTTP-Referer"] = site_url
        if site_name:
            headers["X-Title"] = site_name

        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key=self.api_key,
            default_headers=headers if headers else None,
        )
        self.model_name = model_name
        self.default_model = model_name

    def _messages_into(self, messages: List[common.Message]) -> List[Dict[str, Any]]:
        openai_messages = []

        for message in messages:
            content_parts = []
            tool_calls = []
            tool_results = []

            # first pass: collect all content blocks by type
            for block in message.content:
                if isinstance(block, common.TextRaw):
                    content_parts.append({"type": "text", "text": block.text})
                elif isinstance(block, common.ToolUse):
                    # ensure arguments are properly serialized
                    arguments = block.input
                    if not isinstance(arguments, str):
                        try:
                            arguments = json.dumps(arguments)
                        except (TypeError, ValueError) as e:
                            logger.warning(
                                f"Failed to serialize tool arguments: {e}, using str conversion"
                            )
                            arguments = str(arguments)

                    tool_calls.append(
                        {
                            "id": block.id,
                            "type": "function",
                            "function": {"name": block.name, "arguments": arguments},
                        }
                    )
                elif isinstance(block, common.ToolResult):
                    tool_results.append(block)

            # handle tool results as separate messages (OpenAI format requirement)
            if tool_results:
                # first add the main message if it has content
                if content_parts or tool_calls:
                    openai_message = {"role": message.role}
                    if content_parts:
                        if (
                            len(content_parts) == 1
                            and content_parts[0]["type"] == "text"
                        ):
                            openai_message["content"] = content_parts[0]["text"]
                        else:
                            openai_message["content"] = content_parts  # type: ignore
                    elif message.role == "user":
                        # OpenAI requires content for user messages
                        openai_message["content"] = ""

                    if tool_calls:
                        openai_message["tool_calls"] = tool_calls  # type: ignore

                    openai_messages.append(openai_message)

                # then add each tool result as separate messages
                for tool_result in tool_results:
                    openai_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_result.tool_use_id,
                            "content": tool_result.content,
                        }
                    )
            else:
                # regular message without tool results
                if content_parts or tool_calls or message.role == "user":
                    openai_message = {"role": message.role}
                    if content_parts:
                        if (
                            len(content_parts) == 1
                            and content_parts[0]["type"] == "text"
                        ):
                            openai_message["content"] = content_parts[0]["text"]
                        else:
                            openai_message["content"] = content_parts  # type: ignore
                    elif not tool_calls and message.role == "user":
                        # OpenAI requires content for user messages
                        openai_message["content"] = ""

                    if tool_calls:
                        openai_message["tool_calls"] = tool_calls  # type: ignore

                    openai_messages.append(openai_message)

        return openai_messages

    def _tools_into(
        self, tools: List[common.Tool] | None
    ) -> List[Dict[str, Any]] | None:
        if not tools:
            return None

        openai_tools = []
        for tool in tools:
            # validate required tool fields
            name = tool.get("name")
            if not name:
                logger.warning(f"Skipping tool with missing name: {tool}")
                continue

            description = tool.get("description", "")
            parameters = tool.get("input_schema", {})

            # basic validation of parameter schema
            if parameters and not isinstance(parameters, dict):
                logger.warning(
                    f"Tool {name} has invalid parameter schema, using empty schema"
                )
                parameters = {}

            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )

        if not openai_tools:
            logger.warning("No valid tools found after validation")
            return None

        return openai_tools

    def _completion_into(self, response: Any) -> common.Completion:
        content_blocks = []

        message = response.choices[0].message

        # handle tool calls
        if message.tool_calls:
            # standard tool calls handling
            for tool_call in message.tool_calls:
                # parse arguments if they're a JSON string
                try:
                    if isinstance(tool_call.function.arguments, str):
                        arguments = json.loads(tool_call.function.arguments)
                    else:
                        arguments = tool_call.function.arguments
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(
                        f"Failed to parse tool call arguments: {e}, using raw arguments"
                    )
                    arguments = tool_call.function.arguments

                content_blocks.append(
                    common.ToolUse(
                        name=tool_call.function.name, input=arguments, id=tool_call.id
                    )
                )

            # add any remaining text content if present
            if message.content:
                content_blocks.append(common.TextRaw(message.content))
        elif message.content:
            # just regular text content
            content_blocks.append(common.TextRaw(message.content))

        # determine stop reason
        finish_reason = response.choices[0].finish_reason
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

        # get token usage
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        return common.Completion(
            role="assistant",
            content=content_blocks,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=stop_reason,
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
        openai_messages = self._messages_into(messages)

        # insert system prompt at the beginning if provided
        if system_prompt:
            openai_messages.insert(0, {"role": "system", "content": system_prompt})

        # build request parameters
        request_params = {
            "model": chosen_model,
            "messages": openai_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # "provider": {"order": ["cerebras", "groq"]}
        }

        # add tools if provided
        openai_tools = self._tools_into(tools)
        if openai_tools:
            request_params["tools"] = openai_tools
            if tool_choice:
                request_params["tool_choice"] = {
                    "type": "function",
                    "function": {"name": tool_choice},
                }

        try:
            logger.info(
                f"OpenRouter request - model: {chosen_model}, temperature: {temperature}, max_tokens: {max_tokens}"
            )
            if openai_tools:
                logger.info(
                    f"OpenRouter request includes {len(openai_tools)} tools: {[tool['function']['name'] for tool in openai_tools]}"
                )
            if tool_choice:
                logger.info(
                    f"OpenRouter request with forced tool choice: {tool_choice}"
                )

            telemetry = LLMTelemetry()
            telemetry.start_timing()

            # make the API call
            response = await self.client.chat.completions.create(**request_params)

            # log telemetry
            if hasattr(response, "usage") and response.usage:
                telemetry.log_completion(
                    model=chosen_model,
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                    temperature=temperature,
                    has_tools=openai_tools is not None,
                    provider="OpenRouter",
                )

            # convert response to common format
            completion = self._completion_into(response)

            # enhanced logging for tool calls debugging
            tool_use_blocks = [
                block
                for block in completion.content
                if isinstance(block, common.ToolUse)
            ]
            if tool_use_blocks:
                logger.info(
                    f"OpenRouter response includes {len(tool_use_blocks)} tool calls: {[block.name for block in tool_use_blocks]}"
                )

            logger.info(
                f"OpenRouter response - content_blocks: {len(list(completion.content))}, stop_reason: {completion.stop_reason}"
            )

            return completion

        except Exception as e:
            logger.error(f"OpenRouter API error: {e}")
            raise


if __name__ == "__main__":
    import asyncio

    async def test_openrouter():
        # initialize client with OpenRouter API
        # note: This requires OPENROUTER_API_KEY environment variable to be set
        client = OpenRouterLLM(
            model_name="openai/gpt-4o-mini",  # Using a common, cost-effective model for testing
            site_url="https://example.com",  # Optional app attribution
            site_name="Test App",  # Optional app attribution
        )

        # define a test tool (properly typed)
        tools: List[common.Tool] = [
            {
                "name": "get_weather",
                "description": "Get the current weather in a given location",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city and state, e.g. San Francisco, CA",
                        },
                        "unit": {
                            "type": "string",
                            "enum": ["celsius", "fahrenheit"],
                            "description": "The unit of temperature",
                        },
                    },
                    "required": ["location"],
                },
            }
        ]

        # create test messages
        messages = [
            common.InternalMessage(
                role="user",
                content=[common.TextRaw("What's the weather like in San Francisco?")],
            )
        ]

        try:
            # first request - expecting tool use
            print("Sending request to OpenRouter with tool support...")
            completion = await client.completion(
                messages=messages, max_tokens=200, temperature=0.7, tools=tools
            )

            # print the response
            print("\nFirst response from OpenRouter:")
            tool_call = None
            for block in completion.content:
                if isinstance(block, common.TextRaw):
                    print(f"Text: {block.text}")
                elif isinstance(block, common.ToolUse):
                    print(f"Tool call: {block.name}")
                    print(f"Arguments: {block.input}")
                    tool_call = block

            print(
                f"\nTokens used - Input: {completion.input_tokens}, Output: {completion.output_tokens}"
            )
            print(f"Stop reason: {completion.stop_reason}")

            # if we got a tool call, simulate tool response
            if tool_call:
                # add assistant message with tool call
                messages.append(
                    common.InternalMessage(
                        role="assistant", content=list(completion.content)
                    )
                )

                # add tool result
                messages.append(
                    common.InternalMessage(
                        role="user",
                        content=[
                            common.ToolResult(
                                content="The weather in San Francisco is 72°F (22°C) and sunny.",
                                tool_use_id=tool_call.id,
                                name=tool_call.name,
                            )
                        ],  # type: ignore[list-item]
                    )
                )

                # get final response
                print("\n--- Sending follow-up with tool result ---")
                final_completion = await client.completion(
                    messages=messages, max_tokens=200, temperature=0.7, tools=tools
                )

                print("\nFinal response:")
                for block in final_completion.content:
                    if isinstance(block, common.TextRaw):
                        print(block.text)

                print(
                    f"\nTokens used - Input: {final_completion.input_tokens}, Output: {final_completion.output_tokens}"
                )

        except Exception as e:
            print(f"Error during test: {e}")
            print(
                "Make sure OPENROUTER_API_KEY environment variable is set with a valid API key"
            )

    # run the test
    asyncio.run(test_openrouter())
