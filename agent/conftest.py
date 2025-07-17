import pytest
import asyncio
import gc
from llm.utils import llm_clients_cache

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None



@pytest.fixture(scope="session", autouse=True)
def load_env_for_tests():
    """Load .env file for tests if python-dotenv is available."""
    if load_dotenv:
        load_dotenv()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def cleanup_httpx_clients():
    """Ensure httpx clients in Gemini LLM are properly closed before event loop shutdown."""
    yield

    # Force garbage collection while event loop is still running
    # This ensures any httpx clients close their connections properly
    await asyncio.sleep(0)  # Let pending tasks complete

    # Access the Gemini client's httpx client and close it if needed
    for client in llm_clients_cache.values():
        if hasattr(client, 'client') and hasattr(client.client, '_async_client'):
            # Handle CachedLLM wrapper
            gemini_client = client.client
            if hasattr(gemini_client, '_async_client') and hasattr(gemini_client._async_client, '_httpx_client'):
                httpx_client = gemini_client._async_client._httpx_client
                if httpx_client and not httpx_client.is_closed:
                    await httpx_client.aclose()
        elif hasattr(client, '_async_client') and hasattr(client._async_client, '_httpx_client'):
            # Direct GeminiLLM client
            httpx_client = client._async_client._httpx_client
            if httpx_client and not httpx_client.is_closed:
                await httpx_client.aclose()

    # Force garbage collection to clean up any remaining references
    gc.collect()
