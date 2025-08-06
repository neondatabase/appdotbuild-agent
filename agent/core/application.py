from typing import Protocol, Any
from dataclasses import dataclass, field
from typing import Optional, Dict


class ApplicationBase(Protocol):
    @property
    def current_state(self) -> str: ...
    @property
    def state_output(self) -> dict: ...
    @property
    def is_completed(self) -> bool: ...
    def maybe_error(self) -> str | None: ...
    def is_agent_search_failed_error(self) -> bool: 
        """Check if the error is an AgentSearchFailedException"""
        ...


@dataclass
class BaseApplicationContext:
    """Base context class with common fields for all FSM applications"""
    user_prompt: str
    feedback_data: Optional[str] = None
    files: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None
    error_type: Optional[str] = None  # Store the exception class name
    
    def dump_base(self) -> dict:
        """Dump base fields to a dictionary"""
        return {
            "user_prompt": self.user_prompt,
            "feedback_data": self.feedback_data,
            "files": self.files,
            "error": self.error,
            "error_type": self.error_type,
        }


class BaseFSMApplication:
    """Base class for FSM applications with common functionality"""
    
    def __init__(self, client: Any, fsm: Any):
        self.client = client
        self.fsm = fsm
    
    def maybe_error(self) -> str | None:
        """Get the error message if any"""
        return self.fsm.context.error
    
    def is_agent_search_failed_error(self) -> bool:
        """Check if the error is an AgentSearchFailedException"""
        return self.fsm.context.error_type == "AgentSearchFailedException"
