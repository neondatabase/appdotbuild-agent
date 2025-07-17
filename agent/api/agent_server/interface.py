from typing import Protocol
from anyio.streams.memory import MemoryObjectSendStream
from api.agent_server.models import AgentRequest, AgentSseEvent


class AgentInterface(Protocol):
    def __init__(self, *args, **kwargs):
        pass

    async def process(self, request: AgentRequest, event_tx: MemoryObjectSendStream[AgentSseEvent]) -> None:
        ...
