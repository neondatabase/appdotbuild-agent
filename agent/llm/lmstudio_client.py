from typing import List, Dict, Any
import json
import re
from llm import common
from log import get_logger
from llm.openai_client import OpenAILLM

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


class LMStudioLLM(OpenAILLM):
    """
    LM Studio client implemented as an OpenAI-compatible subclass.
    Reuses the OpenAI format transformation logic (messages, tools, completion parsing).
    """

    provider_name = "LMStudio"

    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        model_name: str = "loaded-model",
    ):
        # LM Studio ignores API key but OpenAI client requires a value
        logger.info(f"Initializing LMStudioLLM client with base URL: {base_url}")
        super().__init__(
            model_name=model_name,
            api_key="lm-studio",
            base_url=base_url,
            provider_name=self.provider_name,
        )

    # _messages_into, _tools_into, and _completion_into inherited from OpenAILLM
    # We only override completion to preserve legacy behavior (parsing <tool_call> fallbacks).
    def _messages_into(self, messages: List[common.Message]) -> List[Dict[str, Any]]:
        # Delegate entirely to base class implementation
        return super()._messages_into(messages)  # type: ignore[attr-defined]

    def _tools_into(
        self, tools: List[common.Tool] | None
    ) -> List[Dict[str, Any]] | None:
        return super()._tools_into(tools)  # type: ignore[attr-defined]

    def _completion_into(self, response: Any) -> common.Completion:
        completion = super()._completion_into(response)  # type: ignore[attr-defined]
        # Fallback parsing for inline <tool_call> tags still needed for some legacy models
        new_blocks: list[common.ContentBlock] = []
        for block in completion.content:
            if isinstance(block, common.TextRaw) and "<tool_call>" in block.text:
                parsed_tool_uses, remaining = parse_tool_calls_from_content(block.text)
                if remaining:
                    new_blocks.append(common.TextRaw(remaining))
                new_blocks.extend(parsed_tool_uses)
            else:
                new_blocks.append(block)
        return common.Completion(
            role="assistant",
            content=new_blocks,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            stop_reason=completion.stop_reason,
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
        # Defer to OpenAI-compatible implementation (includes telemetry)
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
                            # Construct ToolResult with positional args to match dataclass definition:
                            # ToolResult(content: str, tool_use_id: str | None = None, name: str | None = None, is_error: bool | None = None)
                            common.ToolResult(
                                "The weather in San Francisco is 72°F (22°C) and sunny.",
                                tool_call.id,
                                tool_call.name,
                                False,
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
