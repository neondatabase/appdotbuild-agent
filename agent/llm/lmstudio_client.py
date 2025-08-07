from typing import List, Dict, Any, Literal, cast
from openai import AsyncOpenAI
import json
import re
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


def parse_tool_calls_from_content(content: str) -> tuple[List[common.ToolUse], str]:
    """Parse tool calls from message content when they're formatted as XML-like tags.

    Returns:
        tuple of (list of ToolUse objects, remaining content after removing tool calls)
    """
    tool_uses = []
    remaining_content = content

    try:
        # Look for tool calls in format: <tool_call><function=name><parameter=key>value</parameter>...</function></tool_call>
        tool_call_pattern = r"<tool_call>(.*?)</tool_call>"
        function_pattern = r"<function=(\w+)>(.*?)</function>"
        param_pattern = r"<parameter=(\w+)>(.*?)</parameter>"

        tool_calls_found = re.findall(tool_call_pattern, content, re.DOTALL)

        for i, tool_call_match in enumerate(tool_calls_found):
            function_match = re.search(function_pattern, tool_call_match, re.DOTALL)
            if function_match:
                function_name = function_match.group(1)
                function_content = function_match.group(2)

                # Extract parameters
                params = {}
                for param_match in re.finditer(
                    param_pattern, function_content, re.DOTALL
                ):
                    param_name = param_match.group(1)
                    param_value = param_match.group(2).strip()

                    # Try to parse JSON values
                    try:
                        params[param_name] = json.loads(param_value)
                    except (json.JSONDecodeError, ValueError):
                        # If not JSON, use as string
                        params[param_name] = param_value

                tool_uses.append(
                    common.ToolUse(
                        name=function_name,
                        input=params,
                        id=f"tool_call_{i}",  # Generate an ID since it's not provided
                    )
                )

                logger.info(
                    f"Successfully parsed tool call from content: {function_name} with params: {params}"
                )

        # Remove all tool calls from content
        if tool_calls_found:
            remaining_content = re.sub(
                tool_call_pattern, "", content, flags=re.DOTALL
            ).strip()

    except Exception as e:
        logger.warning(
            f"Failed to parse tool call from content: {e}, keeping original content"
        )

    return tool_uses, remaining_content


class LMStudioLLM:
    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        model_name: str = "loaded-model",
    ):
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key="lm-studio",  # LM Studio doesn't require a real API key
        )
        self.model_name = model_name
        self.default_model = model_name

    def _messages_into(self, messages: List[common.Message]) -> List[Dict[str, Any]]:
        openai_messages = []

        for message in messages:
            content_parts = []
            tool_calls = []
            tool_results = []

            # First pass: collect all content blocks by type
            for block in message.content:
                if isinstance(block, common.TextRaw):
                    content_parts.append({"type": "text", "text": block.text})
                elif isinstance(block, common.ToolUse):
                    # Ensure arguments are properly serialized
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

            # Handle tool results as separate messages (OpenAI format requirement)
            if tool_results:
                # First add the main message if it has content
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

                # Then add each tool result as separate messages
                for tool_result in tool_results:
                    openai_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_result.tool_use_id,
                            "content": tool_result.content,
                        }
                    )
            else:
                # Regular message without tool results
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
            # Validate required tool fields
            name = tool.get("name")
            if not name:
                logger.warning(f"Skipping tool with missing name: {tool}")
                continue

            description = tool.get("description", "")
            parameters = tool.get("input_schema", {})

            # Basic validation of parameter schema
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

        # Handle tool calls
        if message.tool_calls:
            # Standard tool calls handling
            for tool_call in message.tool_calls:
                # Parse arguments if they're a JSON string
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

            # Add any remaining text content if present
            if message.content:
                content_blocks.append(common.TextRaw(message.content))
        elif message.content:
            # Check if content contains tool calls in XML format (workaround for some LMStudio models)
            if "<tool_call>" in message.content:
                logger.info(
                    "Detected potential tool call in message content, attempting to parse..."
                )
                parsed_tool_uses, remaining_content = parse_tool_calls_from_content(
                    message.content
                )

                # Add remaining content first if any
                if remaining_content:
                    content_blocks.append(common.TextRaw(remaining_content))

                # Then add parsed tool uses
                content_blocks.extend(parsed_tool_uses)
            else:
                # Just regular text content
                content_blocks.append(common.TextRaw(message.content))

        # Determine stop reason
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

        # Get token usage
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

        # Insert system prompt at the beginning if provided
        if system_prompt:
            openai_messages.insert(0, {"role": "system", "content": system_prompt})

        # Build request parameters
        request_params = {
            "model": chosen_model,
            "messages": openai_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Add tools if provided
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
                f"LM Studio request - model: {chosen_model}, temperature: {temperature}, max_tokens: {max_tokens}"
            )
            if openai_tools:
                logger.info(
                    f"LM Studio request includes {len(openai_tools)} tools: {[tool['function']['name'] for tool in openai_tools]}"
                )
            if tool_choice:
                logger.info(f"LM Studio request with forced tool choice: {tool_choice}")

            telemetry = LLMTelemetry()
            telemetry.start_timing()

            # Make the API call
            response = await self.client.chat.completions.create(**request_params)

            # Log telemetry
            if hasattr(response, "usage") and response.usage:
                telemetry.log_completion(
                    model=chosen_model,
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                    temperature=temperature,
                    has_tools=openai_tools is not None,
                    provider="LMStudio",
                )

            # Convert response to common format
            completion = self._completion_into(response)

            # Enhanced logging for tool calls debugging
            tool_use_blocks = [
                block
                for block in completion.content
                if isinstance(block, common.ToolUse)
            ]
            if tool_use_blocks:
                logger.info(
                    f"LM Studio response includes {len(tool_use_blocks)} tool calls: {[block.name for block in tool_use_blocks]}"
                )

            logger.info(
                f"LM Studio response - content_blocks: {len(list(completion.content))}, stop_reason: {completion.stop_reason}"
            )

            return completion

        except Exception as e:
            logger.error(f"LM Studio API error: {e}")
            raise


if __name__ == "__main__":
    import asyncio

    async def test_lmstudio():
        # Initialize client with local LM Studio server
        client = LMStudioLLM(base_url="http://127.0.0.1:1234/v1")

        # Define a test tool (properly typed)
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

        # Create test messages
        messages = [
            common.InternalMessage(
                role="user",
                content=[common.TextRaw("What's the weather like in San Francisco?")],
            )
        ]

        try:
            # First request - expecting tool use
            print("Sending request to LM Studio with tool support...")
            completion = await client.completion(
                messages=messages, max_tokens=200, temperature=0.7, tools=tools
            )

            # Print the response
            print("\nFirst response from LM Studio:")
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

            # If we got a tool call, simulate tool response
            if tool_call:
                # Add assistant message with tool call
                messages.append(
                    common.InternalMessage(
                        role="assistant", content=list(completion.content)
                    )
                )

                # Add tool result
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

                # Get final response
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
                "Make sure LM Studio is running on http://127.0.0.1:1234 with a model loaded that supports function calling"
            )

    # Run the test
    asyncio.run(test_lmstudio())
