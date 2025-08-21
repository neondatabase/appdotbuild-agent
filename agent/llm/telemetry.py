"""Common telemetry utilities for LLM providers."""

import time
import json
import atexit
import os
import signal
import threading
from typing import Optional, Any, Dict
from log import get_logger

logger = get_logger(__name__)

# global accumulator for cumulative telemetry stats per model
_cumulative_stats: Dict[str, Dict[str, int | float]] = {}
_cumulative_enabled = os.getenv("CUMULATIVE_TELEMETRY_LOG") is not None
_stats_lock = threading.Lock()
_call_count_since_save = 0


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
        input_tokens: Optional[int],
        output_tokens: Optional[int],
        temperature: Optional[float] = None,
        has_tools: bool = False,
        provider: Optional[str] = None,
        cache_creation_input_tokens: Optional[int] = None,
        cache_read_input_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        """
        Log LLM completion telemetry in a consistent format.

        Args:
            model: The model name/identifier
            input_tokens: Number of input/prompt tokens (can be None)
            output_tokens: Number of output/completion tokens (can be None)
            temperature: Temperature setting (optional)
            has_tools: Whether tools/functions were provided
            provider: LLM provider name (optional)
            cache_creation_input_tokens: Number of tokens used for cache creation (optional)
            cache_read_input_tokens: Number of tokens read from cache (optional)
            **kwargs: Additional provider-specific metrics
        """
        if self.start_time is None:
            logger.warning("Telemetry timing was not started")
            elapsed_time = 0.0
        else:
            elapsed_time = time.time() - self.start_time

        # validate token counts make sense
        self._validate_tokens(input_tokens, output_tokens, provider)

        # keep original values for logging, use 0 only for arithmetic
        input_tokens_display = "N/A" if input_tokens is None else str(input_tokens)
        output_tokens_display = "N/A" if output_tokens is None else str(output_tokens)

        # for total calculation, treat None as 0
        input_for_total = input_tokens if input_tokens is not None else 0
        output_for_total = output_tokens if output_tokens is not None else 0
        total_tokens = input_for_total + output_for_total

        # Build the log message
        message_parts = [
            "LLM Request completed",
            f"Model: {model}",
            f"Input tokens: {input_tokens_display}",
            f"Output tokens: {output_tokens_display}",
            f"Total tokens: {total_tokens}",
            f"Duration: {elapsed_time:.2f}s",
            f"Has tools: {has_tools}",
        ]

        if temperature is not None:
            message_parts.append(f"Temperature: {temperature}")

        if provider:
            message_parts.insert(1, f"Provider: {provider}")

        # add cached token info if available
        if cache_creation_input_tokens is not None:
            message_parts.append(
                f"Cache creation tokens: {cache_creation_input_tokens}"
            )
        if cache_read_input_tokens is not None:
            message_parts.append(f"Cache read tokens: {cache_read_input_tokens}")

        # Add any additional provider-specific metrics
        for key, value in kwargs.items():
            message_parts.append(f"{key.replace('_', ' ').title()}: {value}")

        logger.info(" | ".join(message_parts))

        # accumulate stats globally if enabled
        if _cumulative_enabled:
            _accumulate_stats(
                model,
                input_for_total,
                output_for_total,
                elapsed_time,
                cache_creation_input_tokens or 0,
                cache_read_input_tokens or 0,
            )

            # periodically save stats to avoid loss on unexpected termination
            global _call_count_since_save
            _call_count_since_save += 1
            if _call_count_since_save >= 10:  # save every 10 calls
                _periodic_save()
                _call_count_since_save = 0

    def _validate_tokens(
        self,
        input_tokens: Optional[int],
        output_tokens: Optional[int],
        provider: Optional[str],
    ) -> None:
        """validate that token counts make sense for non-empty requests/responses"""
        provider_str = f" for {provider}" if provider else ""

        # raise error if we have None tokens - this indicates a provider integration issue
        # that must be fixed to ensure research data accuracy
        if input_tokens is None:
            raise ValueError(
                f"Input tokens must not be None{provider_str} - provider integration error"
            )

        if output_tokens is None:
            raise ValueError(
                f"Output tokens must not be None{provider_str} - provider integration error"
            )

        # warn for zero tokens as this might be legitimate in some edge cases
        if input_tokens == 0:
            logger.warning(
                f"Input tokens is zero{provider_str} - verify this is expected"
            )

        if output_tokens == 0:
            logger.warning(
                f"Output tokens is zero{provider_str} - verify this is expected"
            )


def _accumulate_stats(
    model: str,
    input_tokens: int,
    output_tokens: int,
    elapsed_time: float,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> None:
    """accumulate telemetry stats for a model"""
    with _stats_lock:
        if model not in _cumulative_stats:
            _cumulative_stats[model] = {
                "total_calls": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_time_seconds": 0.0,
                "total_cache_creation_tokens": 0,
                "total_cache_read_tokens": 0,
            }

        _cumulative_stats[model]["total_calls"] += 1
        _cumulative_stats[model]["total_input_tokens"] += input_tokens
        _cumulative_stats[model]["total_output_tokens"] += output_tokens
        _cumulative_stats[model]["total_time_seconds"] += elapsed_time
        _cumulative_stats[model]["total_cache_creation_tokens"] += cache_creation_tokens
        _cumulative_stats[model]["total_cache_read_tokens"] += cache_read_tokens


def save_cumulative_stats() -> None:
    """save cumulative telemetry stats to file specified by CUMULATIVE_TELEMETRY_LOG"""
    if not _cumulative_enabled:
        return

    log_file = os.getenv("CUMULATIVE_TELEMETRY_LOG")
    if not log_file:
        return

    with _stats_lock:
        if not _cumulative_stats:
            return

        try:
            with open(log_file, "w") as f:
                json.dump(_cumulative_stats, f, indent=2)
            logger.info(f"Saved cumulative telemetry stats to {log_file}")
        except Exception as e:
            logger.error(
                f"Failed to save cumulative telemetry stats to {log_file}: {e}"
            )


def _periodic_save() -> None:
    """periodic save without excessive logging"""
    if not _cumulative_enabled:
        return

    log_file = os.getenv("CUMULATIVE_TELEMETRY_LOG")
    if not log_file:
        return

    with _stats_lock:
        if not _cumulative_stats:
            return

        try:
            with open(log_file, "w") as f:
                json.dump(_cumulative_stats, f, indent=2)
        except Exception as e:
            logger.error(
                f"Failed to save cumulative telemetry stats to {log_file}: {e}"
            )


def _signal_handler(signum: int, frame) -> None:
    """handle termination signals by saving telemetry before exit"""
    logger.info(f"Received signal {signum}, saving telemetry before exit")
    save_cumulative_stats()
    # re-raise the signal with default handler to ensure proper termination
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


# register atexit handler and signal handlers if cumulative telemetry is enabled
if _cumulative_enabled:
    atexit.register(save_cumulative_stats)
    # register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
