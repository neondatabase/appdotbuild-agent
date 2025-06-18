import os
import logging
from typing import Dict, Any, Optional
import dagger
from dotnet_agent.application import DotNetFSMApplication

logger = logging.getLogger(__name__)


class DotNetAgentSession:
    """Session manager for .NET agent applications"""
    
    def __init__(self, client: dagger.Client):
        self.client = client
        self.fsm_app: Optional[DotNetFSMApplication] = None
    
    async def create_application(self, user_prompt: str, settings: Dict[str, Any] = None) -> DotNetFSMApplication:
        """Create a new .NET application"""
        logger.info(f"Creating new .NET application with prompt: {user_prompt}")
        self.fsm_app = await DotNetFSMApplication.start_fsm(self.client, user_prompt, settings)
        return self.fsm_app
    
    async def get_application_status(self) -> Dict[str, Any]:
        """Get current application status"""
        if not self.fsm_app:
            return {"error": "No application created"}
        
        return {
            "state": self.fsm_app.current_state,
            "output": self.fsm_app.state_output,
            "actions": self.fsm_app.available_actions,
            "is_completed": self.fsm_app.is_completed,
            "error": self.fsm_app.maybe_error()
        }
    
    async def confirm_state(self):
        """Confirm current state and proceed"""
        if not self.fsm_app:
            raise ValueError("No application created")
        await self.fsm_app.confirm_state()
    
    async def apply_feedback(self, feedback: str):
        """Apply feedback to the application"""
        if not self.fsm_app:
            raise ValueError("No application created")
        await self.fsm_app.apply_changes(feedback)
    
    async def get_diff(self, snapshot: Dict[str, str] = None) -> str:
        """Get diff between current state and snapshot"""
        if not self.fsm_app:
            raise ValueError("No application created")
        return await self.fsm_app.get_diff_with(snapshot or {})
    
    async def complete_application(self):
        """Complete the application by confirming all states"""
        if not self.fsm_app:
            raise ValueError("No application created")
        await self.fsm_app.complete_fsm()


async def create_dotnet_session() -> DotNetAgentSession:
    """Create a new .NET agent session"""
    client = dagger.Connection(dagger.Config(log_output=open(os.devnull, "w")))
    return DotNetAgentSession(await client.__aenter__())