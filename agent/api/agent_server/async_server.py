"""
FastAPI implementation for the agent server.

This server handles API requests initiated by clients (e.g., test clients),
coordinates agent logic using components from `core` and specific agent
implementations like `trpc_agent`. It utilizes `models.py` for
request/response validation and interacts with LLMs via the `llm` wrappers
(indirectly through agents).

Refer to `architecture.puml` for a visual overview.
"""
from typing import AsyncGenerator
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import uvicorn
from fire import Fire
import dagger
import os
import json
from brotli_asgi import BrotliMiddleware

from api.agent_server.models import (
    AgentRequest,
    AgentSseEvent,
    AgentMessage,
    AgentStatus,
    MessageKind,
    ErrorResponse,
    ExternalContentBlock
)
from api.agent_server.interface import AgentInterface
from trpc_agent.agent_session import TrpcAgentSession
from api.agent_server.template_diff_impl import TemplateDiffAgentImplementation
from api.config import CONFIG

from log import get_logger, configure_uvicorn_logging, set_trace_id, clear_trace_id

logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Async Agent Server API")
    yield
    logger.info("Shutting down Async Agent Server API")


app = FastAPI(
    title="Async Agent Server API",
    description="Async API for communication between the Platform (Backend) and the Agent Server",
    version="1.0.0",
    lifespan=lifespan
)

# add Brotli compression middleware with optimized settings for SSE
app.add_middleware(
    BrotliMiddleware,
    quality=4,  # balanced compression/speed for streaming
    minimum_size=500,  # compress responses >= 500 bytes
    gzip_fallback=True  # fallback to gzip for older clients
)

bearer_scheme = HTTPBearer(auto_error=False)


async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    valid_token = CONFIG.builder_token
    if not valid_token:
        logger.info("No token configured, skipping authentication")
        return True

    if not credentials or not credentials.scheme == "Bearer":
        logger.info("Missing authentication token")
        raise HTTPException(
            status_code=401,
            detail="Unauthorized - missing authentication token"
        )

    if credentials.scheme.lower() != "bearer" or credentials.credentials != valid_token:
        logger.info("Invalid authentication token")
        raise HTTPException(
            status_code=403,
            detail="Unauthorized - invalid authentication token"
        )

    return True


class SessionManager:
    def __init__(self):
        self.sessions = {}

    def get_or_create_session[T: AgentInterface](
        self,
        client: dagger.Client,
        request: AgentRequest,
        agent_class: type[T],
        *args,
        **kwargs
    ) -> T:
        session_id = f"{request.application_id}:{request.trace_id}"

        #if session_id in self.sessions:
        #    logger.info(f"Reusing existing session for {session_id}")
        #    return self.sessions[session_id]

        logger.info(f"Creating new agent session for {session_id}")
        agent = agent_class(
            client=client,
            application_id=request.application_id,
            trace_id=request.trace_id,
            settings=request.settings,
            *args,
            **kwargs
        )
        #self.sessions[session_id] = agent
        return agent

    def cleanup_session(self, application_id: str, trace_id: str) -> None:
        session_id = f"{application_id}:{trace_id}"
        if session_id in self.sessions:
            logger.info(f"Removing session for {session_id}")
            del self.sessions[session_id]

session_manager = SessionManager()

async def run_agent[T: AgentInterface](
    request: AgentRequest,
    agent_class: type[T],
    *args,
    **kwargs,
) -> AsyncGenerator[str, None]:
    logger.info(f"Running agent for session {request.application_id}:{request.trace_id}")

    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        # Establish Dagger connection for the agent's execution context
        agent = session_manager.get_or_create_session(client, request, agent_class, *args, **kwargs)

        event_tx, event_rx = anyio.create_memory_object_stream[AgentSseEvent](max_buffer_size=0)
        keep_alive_tx = event_tx.clone()  # Clone the sender for use in the keep-alive task
        final_state = None

        # Use this flag to control the keep-alive task
        keep_alive_running = True

        async def send_keep_alive():
            try:
                # Use shorter sleep intervals to be more responsive
                keep_alive_interval = 30
                sleep_interval = 0.5  # Check every 500ms
                elapsed = 0.0

                while keep_alive_running:
                    await anyio.sleep(sleep_interval)
                    elapsed += sleep_interval

                    if keep_alive_running and elapsed >= keep_alive_interval:
                        keep_alive_event = AgentSseEvent(
                            status=AgentStatus.RUNNING,
                            traceId=request.trace_id,
                            message=AgentMessage(
                                role="assistant",
                                kind=MessageKind.KEEP_ALIVE,
                                content="",
                                messages=[],
                                agentState=None,
                                unifiedDiff=None
                            )
                        )
                        await keep_alive_tx.send(keep_alive_event)
                        elapsed = 0.0  # Reset elapsed time

            except Exception:
                pass
            finally:
                await keep_alive_tx.aclose()

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(agent.process, request, event_tx)

                # Start the keep-alive task
                tg.start_soon(send_keep_alive)

                async with event_rx:
                    async for event in event_rx:
                        # Keep track of the last state in events with non-null state
                        if event.message and event.message.agent_state:
                            final_state = event.message.agent_state

                        # Format SSE event properly with data: prefix and double newline at the end
                        # This ensures compatibility with SSE standard
                        yield f"data: {event.to_json()}\n\n"

                        if event.status == AgentStatus.IDLE:
                            keep_alive_running = False

                            # Only log that we'll clean up later - don't do the actual cleanup here
                            # The actual cleanup happens in the finally block
                            if request.agent_state is None:
                                logger.info(f"Agent idle, will clean up session for {request.application_id}:{request.trace_id} when all events are processed")

        except* Exception as excgroup:
            for e in excgroup.exceptions:
                # Log the specific exception from the group with traceback
                logger.exception(f"Error in SSE generator TaskGroup for trace {request.trace_id}:", exc_info=e)
                error_event = AgentSseEvent(
                    status=AgentStatus.IDLE,
                    traceId=request.trace_id,
                    message=AgentMessage(
                        role="assistant",
                        kind=MessageKind.RUNTIME_ERROR,
                        content=json.dumps([{"role": "assistant", "content": [{"type": "text", "text": f"Error processing request: {str(e)}"}]}]),
                        messages=[ExternalContentBlock(
                            content=f"Error processing request: {str(e)}",
                            #timestamp=datetime.datetime.now(datetime.UTC)
                        )],
                        agentState=None,
                        unifiedDiff=""
                    )
                )
                # Format error SSE event properly
                yield f"data: {error_event.to_json()}\n\n"

                # On error, remove the session entirely
                session_manager.cleanup_session(request.application_id, request.trace_id)
        finally:
            # For requests without agent state or where the session completed, clean up
            # Ensure cleanup happens outside the dagger connection if needed, though session removal should be fine
            if request.agent_state is None and (final_state is None or final_state == {}):
                logger.info(f"Cleaning up completed agent session for {request.application_id}:{request.trace_id}")
                session_manager.cleanup_session(request.application_id, request.trace_id)
                clear_trace_id()


@app.post("/message", response_model=None)
async def message(
    request: AgentRequest,
    token: str = Depends(verify_token)
) -> StreamingResponse:
    """
    Send a message to the agent and stream responses via SSE.

    Platform (Backend) -> Agent Server API Spec:
    POST Request:
    - allMessages: [str] - history of all user messages
    - applicationId: str - required for Agent Server for tracing
    - traceId: str - required - a string used in SSE events
    - agentState: {..} or null - the full state of the Agent to restore from
    - settings: {...} - json with settings with number of iterations etc

    SSE Response:
    - status: "running" | "idle" - defines if the Agent stopped or continues running
    - traceId: corresponding traceId of the input
    - message: {kind, content, agentState, unifiedDiff} - response from the Agent Server

    Args:
        request: The agent request containing all necessary fields
        token: Authentication token (automatically verified by verify_token dependency)

    Returns:
        Streaming response with SSE events according to the API spec
    """
    try:
        logger.info(f"Received message request for application {request.application_id}, trace {request.trace_id}")
        set_trace_id(request.trace_id)
        logger.info("Starting SSE stream for application")
        
        # Use template_id from request if provided, otherwise use CONFIG default
        template_id = request.template_id or CONFIG.default_template_id
        logger.info(f"Using template: {template_id}")
        
        # Validate template_id
        if template_id not in CONFIG.available_templates:
            logger.warning(f"Unknown template {template_id}, falling back to default")
            template_id = CONFIG.default_template_id
        
        agent_type = {
            "template_diff": TemplateDiffAgentImplementation,
            "trpc_agent": TrpcAgentSession,
        }
        
        return StreamingResponse(
            run_agent(request, agent_type[CONFIG.agent_type]),
            media_type="text/event-stream"
        )

    except Exception as e:
        logger.error(f"Error processing message request: {str(e)}")
        # Return an HTTP error response for non-SSE errors
        error_response = ErrorResponse(
            error="Internal Server Error",
            details=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=error_response.to_json()
        )


@app.get("/templates")
async def list_templates():
    """List available templates"""
    return {
        "templates": CONFIG.available_templates,
        "default": CONFIG.default_template_id
    }


@app.get("/health")
async def dagger_healthcheck():
    """Dagger connection health check endpoint"""
    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        # Try a simple Dagger operation to verify connectivity
        container = client.container().from_("alpine:latest")
        version = await container.with_exec(["cat", "/etc/alpine-release"]).stdout()
        return {
            "status": "healthy",
            "dagger_connection": "successful",
            "alpine_version": version.strip()
        }


def main(
    host: str = "0.0.0.0",
    port: int = 8001,
    reload: bool = False,
    log_level: str = "info"
):
    uvicorn.run(
        "api.agent_server.async_server:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
        log_config=configure_uvicorn_logging(),
    )

if __name__ == "__main__":
    Fire(main)
