import uuid
import pytest
from log import get_logger
from api.agent_server.models import AgentSseEvent, AgentStatus, MessageKind
from api.agent_server.agent_api_client import AgentApiClient, DEFAULT_APP_REQUEST, DEFAULT_EDIT_REQUEST
import anyio

logger = get_logger(__name__)

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def trpc_agent(monkeypatch):
    monkeypatch.setenv("CODEGEN_AGENT", "trpc_agent")
    yield


@pytest.fixture
def template_diff(monkeypatch):
    monkeypatch.setenv("CODEGEN_AGENT", "template_diff")
    yield


@pytest.mark.skip(reason="Temporarily disabled")
@pytest.mark.parametrize("agent_type", [trpc_agent, template_diff])
async def test_async_agent_message_endpoint(agent_type):
    async with AgentApiClient() as client:
        events, request = await client.send_message(DEFAULT_APP_REQUEST)

        assert len(events) > 0, f"No SSE events received with agent_type={agent_type}"

        # Verify model objects
        for event in events:
            match event:
                case None:
                    raise ValueError(f"Received None event for {agent_type}")
                case AgentSseEvent():
                    assert event.trace_id == request.trace_id, f"Trace IDs do not match in model objects with agent_type={agent_type}"
                    assert event.status == AgentStatus.IDLE
                    assert event.message.kind in (MessageKind.STAGE_RESULT, MessageKind.REVIEW_RESULT), f"Message kind {event.message.kind} is not one of the expected kinds"



async def test_tracing(caplog, template_diff):
    """Test that sequential SSE responses work properly within a session."""
    async with AgentApiClient() as client:
        initial_events, initial_request = await client.send_message(DEFAULT_APP_REQUEST, trace_id="test-tracing")
        record = caplog.records[-1]
        assert record.trace_id == "test-tracing", f"Trace ID mismatch: {record.trace_id} != test-tracing"

        more_events, more_request = await client.send_message(DEFAULT_APP_REQUEST, trace_id="test-tracing-more")
        record = caplog.records[-1]
        assert record.trace_id == "test-tracing-more", f"Trace ID mismatch: {record.trace_id} != test-tracing-more"


@pytest.mark.skip(reason="Temporarily disabled")
async def test_sequential_sse_responses(trpc_agent):
    """Test that sequential SSE responses work properly within a session."""
    async with AgentApiClient() as client:
        # Initial request
        initial_events, initial_request = await client.send_message(DEFAULT_APP_REQUEST)
        assert len(initial_events) > 0, "No initial events received"

        # First continuation
        first_continuation_events, first_continuation_request = await client.continue_conversation(
            previous_events=initial_events,
            previous_request=initial_request,
            message=DEFAULT_EDIT_REQUEST,
        )
        assert len(first_continuation_events) > 0, "No first continuation events received"
        for event in first_continuation_events:
            assert event.message.kind != MessageKind.RUNTIME_ERROR, "Message kind is RUNTIME_ERROR in first continuation"
            assert event.trace_id == initial_request.trace_id, "Trace IDs don't match in first continuation (model)"

        # # Second continuation - temporarily disabled, not working as expected
        # second_continuation_events, second_continuation_request = await client.continue_conversation(
        #     previous_events=first_continuation_events,
        #     previous_request=first_continuation_request,
        #     message="Add a reset button",
        # )
        # assert len(second_continuation_events) > 0, "No second continuation events received"

        # for event in second_continuation_events:
        #     assert event.message.kind != MessageKind.RUNTIME_ERROR, "Message kind is RUNTIME_ERROR in second continuation"
        #     assert event.trace_id == initial_request.trace_id, "Trace IDs don't match in second continuation (model)"


@pytest.mark.skip(reason="Temporarily disabled")
async def test_session_with_no_state(trpc_agent):
    """Test session behavior when no state is provided in continuation requests."""
    async with AgentApiClient() as client:
        # Generate a fixed trace/chatbot ID to use for all requests
        fixed_trace_id = uuid.uuid4().hex
        fixed_application_id = f"test-bot-{uuid.uuid4().hex[:8]}"

        # First request
        first_events, _ = await client.send_message(
            DEFAULT_APP_REQUEST,
            application_id=fixed_application_id,
            trace_id=fixed_trace_id
        )
        assert len(first_events) > 0, "No events received from first request"

        # Second request - same session, explicitly pass None for agent_state
        second_events, _ = await client.send_message(
            "Add a reset button",
            application_id=fixed_application_id,
            trace_id=fixed_trace_id,
            agent_state=None
        )
        assert len(second_events) > 0, "No events received from second request"

        for event in first_events + second_events:
            assert event.trace_id == fixed_trace_id, f"Trace ID mismatch: {event.trace_id} != {fixed_trace_id}"
            assert event.message.kind != MessageKind.RUNTIME_ERROR, "Message kind is RUNTIME_ERROR during continuation"

@pytest.mark.skip(reason="Temporarily disabled")
async def test_agent_reaches_idle_state(trpc_agent):
    """Test that the agent eventually transitions to IDLE state after processing a simple prompt."""
    async with AgentApiClient() as client:
        # Send a simple "Hello" prompt
        events, _ = await client.send_message("Hello")

        # Check that we received some events
        assert len(events) > 0, "No events received"

        # Verify the final event has IDLE status
        final_event = events[-1]
        assert final_event.status == AgentStatus.IDLE, "Agent did not reach IDLE state"

        assert final_event.message is not None, "Final event has no message"
        assert final_event.message.role == "assistant", "Final message role is not 'assistant'"
        assert final_event.message.kind == MessageKind.REFINEMENT_REQUEST, "Final message kind is not REFINEMENT_REQUEST"
        assert final_event.message.agent_state is None, "Final event has non-null agent state"
        assert final_event.message.unified_diff is None, "Final event has non-null unified diff"


@pytest.mark.skip(reason="Not for CI usage - requires a separate running server")
async def test_concurrent_usage():
    total_requests = 3
    logger.info(f"Starting load test with {total_requests} requests")
    async def run_load_test():
        async with AgentApiClient(base_url="http://0.0.0.0:8001") as client:
            events, request = await client.send_message("Hello")

    tg = anyio.create_task_group()
    async with tg:
        for i in range(total_requests):
            logger.info(f"Starting request {i + 1}/{total_requests}")
            tg.start_soon(run_load_test)
