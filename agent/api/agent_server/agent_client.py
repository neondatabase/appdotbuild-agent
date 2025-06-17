import ujson as json
import uuid
from typing import List, Dict, Any, Tuple, Optional, Callable
from httpx import AsyncClient, ASGITransport

from api.agent_server.models import AgentSseEvent, AgentRequest, UserMessage, ConversationMessage, FileEntry, MessageKind
from api.agent_server.async_server import app, CONFIG
from log import get_logger

logger = get_logger(__name__)

# Re-export MessageKind for convenient import in tests
__all__ = [
    "AgentApiClient",
    "MessageKind",
]

class AgentApiClient:
    """Reusable client for interacting with the Agent API server"""

    def __init__(self, app_instance=None, base_url=None):
        """Initialize the client with an optional app instance or base URL

        Args:
            app_instance: FastAPI app instance for direct ASGI transport
            base_url: External base URL to test against (e.g., "http://18.237.53.81")
        """
        self.app = app_instance or app
        self.base_url = base_url
        self.transport = ASGITransport(app=self.app) if base_url is None else None
        self.client = None

    async def __aenter__(self):
        if self.base_url:
            self.client = AsyncClient(base_url=self.base_url)
        else:
            self.client = AsyncClient(transport=self.transport)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def send_message(self,
                          message: str,
                          messages_history: Optional[List[ConversationMessage]] = None,
                          request: Optional[AgentRequest] = None,
                          application_id: Optional[str] = None,
                          trace_id: Optional[str] = None,
                          agent_state: Optional[Dict[str, Any]] = None,
                          all_files: Optional[List[Dict[str, str]]] = None,
                          template_id: Optional[str] = None,
                          settings: Optional[Dict[str, Any]] = None,
                          auth_token: Optional[str] = CONFIG.builder_token,
                          stream_cb: Optional[Callable[[AgentSseEvent], None]] = None
                         ) -> Tuple[List[AgentSseEvent], AgentRequest]:

        """Send a message to the agent and return the parsed SSE events"""

        if request is None:
            request = self.create_request(message, messages_history, application_id, trace_id, agent_state, all_files, template_id, settings)
        else:
            logger.info(f"Using existing request with trace ID: {request.trace_id}, ignoring some parameters like message, all_files")
            if all_files is not None:
                request.all_files = [FileEntry(**f) for f in all_files]

        url = self.base_url or "http://test"
        url += "/message"
        headers={"Accept": "text/event-stream", "Accept-Encoding": "br, gzip, deflate"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
            logger.debug("Added authorization header")
        else:
            logger.info("No auth token available for authorization")

        async with self.client.stream(
            "POST",
            url,
            json=request.model_dump(by_alias=True),
            headers=headers,
            timeout=None
        ) as response:
            if response.status_code != 200:
                await response.aread()
                raise ValueError(f"Request failed with status code {response.status_code}: {response.json()}")
            events = await self.parse_sse_events(response, stream_cb)
        return events, request

    async def continue_conversation(self,
                                   previous_events: List[AgentSseEvent],
                                   previous_request: AgentRequest,
                                   message: str,
                                   all_files: Optional[List[Dict[str, str]]] = None,
                                   settings: Optional[Dict[str, Any]] = None,
                                   stream_cb: Optional[Callable[[AgentSseEvent], None]] = None
                                  ) -> Tuple[List[AgentSseEvent], AgentRequest]:
        """Continue a conversation using the agent state from previous events."""
        # Use agent_state from the latest event (if any)
        agent_state: Optional[Dict[str, Any]] = None
        for event in reversed(previous_events):
            if event.message and event.message.agent_state is not None:
                agent_state = event.message.agent_state
                break

        # Fallback to the agent_state stored in the previous_request itself
        if agent_state is None:
            agent_state = previous_request.agent_state

        # Reuse the full history that the server already knows about
        all_messages_history: List[ConversationMessage] = (
            list(previous_request.all_messages) if previous_request.all_messages else []
        )

        trace_id = previous_request.trace_id
        application_id = previous_request.application_id

        # Delegate to `send_message`, which will append the new user message
        events, request = await self.send_message(
            message=message,
            messages_history=all_messages_history,
            application_id=application_id,
            trace_id=trace_id,
            agent_state=agent_state,
            all_files=all_files,
            settings=settings,
            stream_cb=stream_cb
        )

        return events, request

    @staticmethod
    def create_request(message: str,
                     messages_history: Optional[List[ConversationMessage]] = None,
                     application_id: Optional[str] = None,
                     trace_id: Optional[str] = None,
                     agent_state: Optional[Dict[str, Any]] = None,
                     all_files: Optional[List[Dict[str, str]]] = None,
                     template_id: Optional[str] = None,
                     settings: Optional[Dict[str, Any]] = None)  -> AgentRequest:
        """Create a request object for the agent API"""

        all_messages_list = list(messages_history) if messages_history else []
        all_messages_list.append(UserMessage(role="user", content=message))

        file_entries: Optional[List[FileEntry]] = None
        if all_files is not None:
            file_entries = [FileEntry(**f) for f in all_files]

        return AgentRequest(
            allMessages=all_messages_list,
            applicationId=application_id or f"test-bot-{uuid.uuid4().hex[:8]}",
            traceId=trace_id or uuid.uuid4().hex,
            agentState=agent_state,
            allFiles=file_entries,
            templateId=template_id,
            settings=settings
        )

    @staticmethod
    async def parse_sse_events(response, stream_cb: Optional[Callable[[AgentSseEvent], None]] = None) -> List[AgentSseEvent]:
        """Parse the SSE events from a response stream"""
        event_objects = []
        buffer = ""

        async for line in response.aiter_lines():
            buffer += line
            if line.strip() == "":  # End of SSE event marked by empty line
                if buffer.startswith("data:"):
                    data_parts = buffer.split("data:", 1)
                    if len(data_parts) > 1:
                        data_str = data_parts[1].strip()
                        try:
                            event_obj = AgentSseEvent.from_json(data_str)
                            event_objects.append(event_obj)
                            if stream_cb:
                                try:
                                    stream_cb(event_obj)
                                except Exception:
                                    logger.exception("Callback failed")
                        except json.JSONDecodeError as e:
                            logger.warning(f"JSON decode error: {e}, data: {data_str[:100]}...")
                        except Exception as e:
                            logger.warning(f"Error parsing SSE event: {e}, data: {data_str[:100]}...")
                buffer = ""

        return event_objects
