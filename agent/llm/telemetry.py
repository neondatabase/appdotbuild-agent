"""Common telemetry utilities for LLM providers."""

import time
from typing import Optional, Any
from log import get_logger

logger = get_logger(__name__)


class LLMTelemetry:
    """Utility class for consistent LLM telemetry logging across providers."""
    
    def __init__(self):
        self.start_time: Optional[float] = None
    
    def start_timing(self) -> None:
        """Start timing an LLM request."""
        self.start_time = time.time()
    
    def log_completion(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        temperature: Optional[float] = None,
        has_tools: bool = False,
        provider: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """
        Log LLM completion telemetry in a consistent format.
        
        Args:
            model: The model name/identifier
            input_tokens: Number of input/prompt tokens
            output_tokens: Number of output/completion tokens
            temperature: Temperature setting (optional)
            has_tools: Whether tools/functions were provided
            provider: LLM provider name (optional)
            **kwargs: Additional provider-specific metrics
        """
        if self.start_time is None:
            logger.warning("Telemetry timing was not started")
            elapsed_time = 0.0
        else:
            elapsed_time = time.time() - self.start_time
        
        total_tokens = input_tokens + output_tokens
        
        # Build the log message
        message_parts = [
            "LLM Request completed",
            f"Model: {model}",
            f"Input tokens: {input_tokens}",
            f"Output tokens: {output_tokens}",
            f"Total tokens: {total_tokens}",
            f"Duration: {elapsed_time:.2f}s",
            f"Has tools: {has_tools}",
        ]
        
        if temperature is not None:
            message_parts.append(f"Temperature: {temperature}")
        
        if provider:
            message_parts.insert(1, f"Provider: {provider}")
        
        # Add any additional provider-specific metrics
        for key, value in kwargs.items():
            message_parts.append(f"{key.replace('_', ' ').title()}: {value}")
        
        logger.info(" | ".join(message_parts))