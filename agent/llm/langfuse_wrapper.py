from langfuse.decorators import langfuse_context, observe
from llm.common import AsyncLLM, Message, Tool, Completion


class LangfuseLLM(AsyncLLM):
    def __init__(self, client: AsyncLLM):
        self.client = client

    @observe(as_type="generation", name="AsyncLLM-generation")
    async def completion(
        self,
        model: str,
        messages: list[Message],
        max_tokens: int,
        temperature: float = 1.0,
        tools: list[Tool] | None = None,
        tool_choice: str | None = None,
        *args,
        **kwargs,
    ) -> Completion:
        langfuse_context.update_current_observation(
            input=messages,
            model=model,
            model_parameters={
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
            metadata=kwargs,
        )
        completion = await self.client.completion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            tool_choice=tool_choice,
            *args,
            **kwargs,
        )
        langfuse_context.update_current_observation(
            output=completion,
            usage={
                "input": completion.input_tokens,
                "output": completion.output_tokens,
            },
        )
        return completion
