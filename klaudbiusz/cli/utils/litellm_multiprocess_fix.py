"""Ugly workaround for litellm's incompatibility with multiprocessing.

litellm creates async logging workers with event loop-bound queues at import time,
which breaks when using joblib/multiprocessing. This is a known bug tracked at:
https://github.com/BerriAI/litellm/issues/14521

Workaround: detach the queue from the logging worker to prevent event loop binding errors.
Also suppresses verbose INFO logs that create duplicates due to handler conflicts.
"""

import logging


def patch_litellm_for_multiprocessing():
    """Disable litellm's async logging worker to prevent event loop issues."""
    import litellm

    # disable all callback infrastructure
    litellm.turn_off_message_logging = True
    litellm.drop_params = True
    litellm.suppress_debug_info = True  # suppress print() statements like "Provider List: ..."
    litellm.success_callback = []
    litellm.failure_callback = []
    litellm._async_success_callback = []
    litellm._async_failure_callback = []

    # detach queue from logging worker to prevent event loop binding
    # see: https://github.com/BerriAI/litellm/issues/14521
    try:
        from litellm.litellm_core_utils.logging_worker import GLOBAL_LOGGING_WORKER

        GLOBAL_LOGGING_WORKER._queue = None
    except Exception:
        pass  # ignore if litellm internals change

    # suppress verbose litellm INFO logs (duplicates due to handler conflicts)
    logging.getLogger('LiteLLM').setLevel(logging.WARNING)
    logging.getLogger('LiteLLM Proxy').setLevel(logging.WARNING)
    logging.getLogger('LiteLLM Router').setLevel(logging.WARNING)
