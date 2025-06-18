"""
.NET Agent Session for the agent server interface.

This module provides the DotNetAgentSession class that implements the AgentInterface
protocol for use with the async agent server.
"""
from typing import Dict, Any, Optional, List
import dagger
from anyio.streams.memory import MemoryObjectSendStream

from api.agent_server.interface import AgentInterface
from api.agent_server.models import (
    AgentSseEvent, AgentMessage, AgentStatus, MessageKind, 
    AgentRequest, UserMessage, 
    ExternalContentBlock, DiffStatEntry
)
from dotnet_agent.application import DotNetFSMApplication, FSMState
from log import get_logger

logger = get_logger(__name__)


class DotNetAgentSession(AgentInterface):
    """
    .NET Agent Session that implements the AgentInterface for the async server.
    
    This class manages .NET application generation through the FSM and provides
    the SSE interface required by the agent server.
    """

    def __init__(self, client: dagger.Client, application_id: str, trace_id: str, settings: Optional[Dict[str, Any]] = None):
        """
        Initialize the .NET Agent Session.

        Args:
            client: Dagger client for containerized operations
            application_id: Unique identifier for the application
            trace_id: Trace ID for tracking the request
            settings: Optional settings for the agent
        """
        self.client = client
        self.application_id = application_id
        self.trace_id = trace_id
        self.settings = settings or {}
        self.fsm_app: Optional[DotNetFSMApplication] = None
        self.previous_diff_hash = None
        
        logger.info(f"Initialized .NET Agent Session for app {application_id}, trace {trace_id}")

    async def process(self, request: AgentRequest, event_tx: MemoryObjectSendStream[AgentSseEvent]) -> None:
        """
        Process the agent request and generate .NET application.

        Args:
            request: The agent request containing messages and context
            event_tx: Event sender for SSE responses
        """
        try:
            logger.info(f"Processing .NET agent request for {self.application_id}")
            
            # Extract user prompt from messages
            user_messages = [msg for msg in request.all_messages if isinstance(msg, UserMessage)]
            if not user_messages:
                raise ValueError("No user messages found in request")
            
            user_prompt = user_messages[-1].content
            logger.info(f"User prompt: {user_prompt}")

            # Initialize or restore FSM application
            if request.agent_state and 'fsm_checkpoint' in request.agent_state:
                # Restore from checkpoint
                logger.info("Restoring FSM from checkpoint")
                checkpoint = request.agent_state['fsm_checkpoint']
                self.fsm_app = await DotNetFSMApplication.load(self.client, checkpoint)
            else:
                # Create new FSM application
                logger.info("Creating new .NET FSM application")
                self.fsm_app = await DotNetFSMApplication.start_fsm(self.client, user_prompt, self.settings)

            # Process based on current state
            await self._process_fsm_state(request, event_tx)

        except Exception as e:
            logger.exception(f"Error processing .NET agent request: {e}")
            await self._send_error_event(event_tx, str(e))

    async def _process_fsm_state(self, request: AgentRequest, event_tx: MemoryObjectSendStream[AgentSseEvent]) -> None:
        """Process the current FSM state and send appropriate events."""
        
        current_state = self.fsm_app.current_state
        logger.info(f"Processing FSM state: {current_state}")

        if current_state in [FSMState.REVIEW_DRAFT, FSMState.REVIEW_APPLICATION]:
            # Send review result
            await self._send_review_event(event_tx)
        elif current_state == FSMState.COMPLETE:
            # Send completion result
            await self._send_completion_event(event_tx, request)
        elif current_state == FSMState.FAILURE:
            # Send error
            error = self.fsm_app.maybe_error() or "Unknown error occurred"
            await self._send_error_event(event_tx, error)
        else:
            # Processing state - advance FSM
            await self._advance_fsm(event_tx)

    async def _advance_fsm(self, event_tx: MemoryObjectSendStream[AgentSseEvent]) -> None:
        """Advance the FSM to the next state."""
        try:
            await self.fsm_app.confirm_state()
            
            # Send stage result after advancement
            await self._send_stage_result(event_tx)
            
        except Exception as e:
            logger.exception(f"Error advancing FSM: {e}")
            await self._send_error_event(event_tx, str(e))

    async def _send_stage_result(self, event_tx: MemoryObjectSendStream[AgentSseEvent]) -> None:
        """Send stage result event."""
        
        current_state = self.fsm_app.current_state
        
        # Generate content message based on state
        if current_state == FSMState.DRAFT:
            content_msg = "🏗️ Generated .NET application structure with models, DTOs, and controllers"
        elif current_state == FSMState.APPLICATION:
            content_msg = "⚙️ Implemented .NET controllers and React frontend"
        else:
            content_msg = f"✅ Completed {current_state} stage"

        # Create unified diff
        unified_diff = await self._generate_unified_diff()
        
        event = AgentSseEvent(
            status=AgentStatus.RUNNING,
            trace_id=self.trace_id,
            message=AgentMessage(
                role="assistant",
                kind=MessageKind.STAGE_RESULT,
                messages=[ExternalContentBlock(content=content_msg)],
                agent_state=self._get_agent_state(),
                unified_diff=unified_diff,
                diff_stat=self._generate_diff_stat(unified_diff)
            )
        )
        
        await event_tx.send(event)

    async def _send_review_event(self, event_tx: MemoryObjectSendStream[AgentSseEvent]) -> None:
        """Send review result event."""
        
        current_state = self.fsm_app.current_state
        
        if current_state == FSMState.REVIEW_DRAFT:
            content_msg = "📋 .NET application draft ready for review. The structure includes models, DTOs, Entity Framework DbContext, and API controller stubs."
        else:
            content_msg = "🎉 .NET application implementation complete! Ready for review and deployment."

        # Generate unified diff
        unified_diff = await self._generate_unified_diff()
        
        event = AgentSseEvent(
            status=AgentStatus.IDLE,
            trace_id=self.trace_id,
            message=AgentMessage(
                role="assistant",
                kind=MessageKind.REVIEW_RESULT,
                messages=[ExternalContentBlock(content=content_msg)],
                agent_state=self._get_agent_state(),
                unified_diff=unified_diff,
                diff_stat=self._generate_diff_stat(unified_diff)
            )
        )
        
        await event_tx.send(event)

    async def _send_completion_event(self, event_tx: MemoryObjectSendStream[AgentSseEvent], request: AgentRequest) -> None:
        """Send completion event."""
        
        content_msg = "🚀 .NET application generation completed successfully!"
        
        # Generate final unified diff
        unified_diff = await self._generate_unified_diff(request.all_files)
        
        event = AgentSseEvent(
            status=AgentStatus.IDLE,
            trace_id=self.trace_id,
            message=AgentMessage(
                role="assistant",
                kind=MessageKind.REVIEW_RESULT,
                messages=[ExternalContentBlock(content=content_msg)],
                agent_state=self._get_agent_state(),
                unified_diff=unified_diff,
                diff_stat=self._generate_diff_stat(unified_diff),
                app_name=self._generate_app_name(),
                commit_message=self._generate_commit_message()
            )
        )
        
        await event_tx.send(event)

    async def _send_error_event(self, event_tx: MemoryObjectSendStream[AgentSseEvent], error_message: str) -> None:
        """Send error event."""
        
        event = AgentSseEvent(
            status=AgentStatus.IDLE,
            trace_id=self.trace_id,
            message=AgentMessage(
                role="assistant",
                kind=MessageKind.RUNTIME_ERROR,
                messages=[ExternalContentBlock(content=f"❌ Error: {error_message}")],
                agent_state=self._get_agent_state(),
                unified_diff="",
                diff_stat=[]
            )
        )
        
        await event_tx.send(event)

    async def _generate_unified_diff(self, all_files: Optional[List] = None) -> str:
        """Generate unified diff for current state."""
        if not self.fsm_app:
            return ""
        
        try:
            # Convert all_files to snapshot format if provided
            snapshot = {}
            if all_files:
                for file_entry in all_files:
                    snapshot[file_entry.path] = file_entry.content
            
            diff = await self.fsm_app.get_diff_with(snapshot)
            return diff
            
        except Exception as e:
            logger.exception(f"Error generating unified diff: {e}")
            return f"# Error generating diff: {e}\n"

    def _generate_diff_stat(self, unified_diff: str) -> List[DiffStatEntry]:
        """Generate diff statistics from unified diff."""
        if not unified_diff:
            return []
        
        diff_stats = []
        current_file = None
        insertions = 0
        deletions = 0
        
        for line in unified_diff.split('\n'):
            if line.startswith('+++'):
                # New file
                if current_file and (insertions > 0 or deletions > 0):
                    diff_stats.append(DiffStatEntry(
                        path=current_file,
                        insertions=insertions,
                        deletions=deletions
                    ))
                
                current_file = line[4:].strip()  # Remove '+++ '
                insertions = 0
                deletions = 0
            elif line.startswith('+') and not line.startswith('+++'):
                insertions += 1
            elif line.startswith('-') and not line.startswith('---'):
                deletions += 1
        
        # Add final file
        if current_file and (insertions > 0 or deletions > 0):
            diff_stats.append(DiffStatEntry(
                path=current_file,
                insertions=insertions,
                deletions=deletions
            ))
        
        return diff_stats

    def _get_agent_state(self) -> Dict[str, Any]:
        """Get current agent state for persistence."""
        if not self.fsm_app:
            return {}
        
        return {
            'current_state': self.fsm_app.current_state,
            'fsm_checkpoint': self.fsm_app.fsm.checkpoint(),
            'application_id': self.application_id,
            'trace_id': self.trace_id
        }

    def _generate_app_name(self) -> str:
        """Generate a suitable app name."""
        if self.fsm_app and self.fsm_app.fsm.context.user_prompt:
            # Simple app name generation from user prompt
            prompt = self.fsm_app.fsm.context.user_prompt.lower()
            words = prompt.replace(" ", "-").replace("_", "-")
            # Take first few words and sanitize
            name_parts = [word for word in words.split("-") if word.isalnum()][:3]
            return "-".join(name_parts) + "-dotnet-app"
        
        return "dotnet-react-app"

    def _generate_commit_message(self) -> str:
        """Generate a suitable commit message."""
        if self.fsm_app and self.fsm_app.fsm.context.user_prompt:
            return f"feat: implement {self.fsm_app.fsm.context.user_prompt}\n\n- Generated .NET Web API with Entity Framework Core\n- Created React frontend with TypeScript\n- Configured PostgreSQL database"
        
        return "feat: implement .NET React application\n\n- Generated complete full-stack application\n- .NET 8 Web API backend\n- React TypeScript frontend"