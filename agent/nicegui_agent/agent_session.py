import logging
from typing import Dict, Any, Optional
import dagger

from nicegui_agent.application import FSMApplication
from api.base_agent_session import BaseAgentSession

logger = logging.getLogger(__name__)


class NiceguiAgentSession(BaseAgentSession):
    def __init__(
        self,
        client: dagger.Client,
        application_id: str | None = None,
        trace_id: str | None = None,
        settings: Optional[Dict[str, Any]] = None,
    ):
        """Initialize a new NiceGUI agent session"""
        super().__init__(client, FSMApplication, application_id, trace_id, settings)
