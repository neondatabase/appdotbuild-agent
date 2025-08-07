import random
from typing import List, Literal
from llm.common import AsyncLLM, Message, Completion, Tool
from log import get_logger

logger = get_logger(__name__)


class AlloyLLM(AsyncLLM):
    """Alloy Agent implementation that combines multiple models in a single conversation thread.

    Models alternate generating responses, unaware they are part of an alloy.
    """

    def __init__(
        self,
        models: List[AsyncLLM],
        selection_strategy: Literal["random", "round_robin"] = "random",
    ):
        if not models:
            raise ValueError("At least one model must be provided")

        self.models = models
        self.selection_strategy = selection_strategy
        self.current_index = 0
        logger.info(
            f"Initialized AlloyLLM with {len(models)} models, strategy: {selection_strategy}"
        )

    @classmethod
    def from_models(
        cls,
        models: List[AsyncLLM],
        selection_strategy: Literal["random", "round_robin"] = "random",
    ) -> "AlloyLLM":
        """Create an AlloyLLM from a list of model instances.

        Args:
            models: List of AsyncLLM instances to combine
            selection_strategy: How to select models ("random" or "round_robin")

        Returns:
            An AlloyLLM instance
        """
        return cls(models, selection_strategy)

    async def completion(
        self,
        messages: list[Message],
        max_tokens: int,
        model: str | None = None,
        temperature: float = 1.0,
        tools: list[Tool] | None = None,
        tool_choice: str | None = None,
        system_prompt: str | None = None,
        *args,
        **kwargs,
    ) -> Completion:
        # select model based on strategy
        if self.selection_strategy == "random":
            selected_model = random.choice(self.models)
            model_idx = self.models.index(selected_model)
        else:  # round_robin
            selected_model = self.models[self.current_index]
            model_idx = self.current_index
            self.current_index = (self.current_index + 1) % len(self.models)

        logger.info(
            f"AlloyLLM selected model index {model_idx} of {len(self.models)}, which is {repr(selected_model)}"
        )

        # delegate to selected model
        return await selected_model.completion(
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
