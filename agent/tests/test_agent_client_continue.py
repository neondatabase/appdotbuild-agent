import pytest
from api.agent_server.agent_client import AgentApiClient
from api.agent_server.models import (
    AgentSseEvent,
    AgentMessage,
    ExternalContentBlock,
    AgentStatus,
    MessageKind,
    AgentRequest,
    UserMessage,
    ConversationMessage,
)

# Force AnyIO to use asyncio backend (trio is optional and not installed in CI)

@pytest.fixture
def anyio_backend():
    """Restrict anyio to use asyncio backend only for this test module."""
    return "asyncio"

@pytest.mark.anyio
async def test_continue_conversation_builds_history(monkeypatch):
    """Ensure continue_conversation reuses previous_request.all_messages and passes them to send_message."""

    # Prepare a previous assistant event
    block = ExternalContentBlock(content="Hello")
    assistant_msg = AgentMessage(role="assistant", kind=MessageKind.STAGE_RESULT, messages=[block])
    prev_event = AgentSseEvent(status=AgentStatus.IDLE, traceId="tid123", message=assistant_msg)

    # Prepare previous request containing a richer history (user + assistant round-trip)
    prev_history: list[ConversationMessage] = [
        UserMessage(role="user", content="Hi"),
        assistant_msg,
    ]

    prev_request = AgentRequest(
        allMessages=prev_history,
        applicationId="app123",
        traceId="tid123",
        agentState={"foo": "bar"},  # Some dummy state
        allFiles=None,
        settings=None,
    )

    # Capture arguments passed to fake_send_message
    captured = {}

    async def fake_send_message(self, *, message, messages_history, application_id, trace_id, agent_state, all_files, settings, stream_cb, auth_token=None, request=None):
        captured.update(
            message=message,
            history=messages_history,
            application_id=application_id,
            trace_id=trace_id,
            agent_state=agent_state,
        )
        # Return empty events and the same request for simplicity
        return [], prev_request

    # Patch send_message
    monkeypatch.setattr(AgentApiClient, "send_message", fake_send_message)

    async with AgentApiClient(app_instance=None, base_url="http://testserver") as client:
        await client.continue_conversation([prev_event], prev_request, message="Follow up")

    # Assertions
    assert captured["message"] == "Follow up"
    # send_message must receive history of same length and role order
    assert len(captured["history"]) == len(prev_request.all_messages)
    assert [m.role for m in captured["history"]] == [m.role for m in prev_request.all_messages]
    # agent_state is forwarded unchanged
    assert captured["agent_state"] == prev_request.agent_state
    assert captured["application_id"] == "app123"
    assert captured["trace_id"] == "tid123" 