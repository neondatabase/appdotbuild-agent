"""
Implementation of the TemplateDiffAgentImplementation for generating applications
with unified diffs. This implementation specializes in creating counter applications
with detailed logging and error handling.
"""
import os
import json
import tempfile
import shutil
import dagger
from typing import Dict, Any, Optional, Tuple

from api.agent_server.interface import AgentInterface
from api.agent_server.models import AgentSseEvent, AgentMessage, AgentStatus, MessageKind

from log import get_logger

logger = get_logger(__name__)


class TemplateDiffAgentImplementation(AgentInterface):
    """
    Agent implementation that generates a counter application with unified diffs.

    This implementation demonstrates how to create a simple application with
    server and frontend components, providing unified diffs for the changes.
    """

    def __init__(self, client: dagger.Client, application_id: str, trace_id: str, settings: Optional[Dict[str, Any]] = None):
        """
        Initialize the TemplateDiffAgentImplementation.

        Args:
            application_id: Unique identifier for the application
            trace_id: Trace ID for tracking the request
            settings: Optional settings for the agent
        """
        self.application_id = application_id
        self.trace_id = trace_id
        self.settings = settings or {}
        self.state = {}
        self.temp_dir = tempfile.mkdtemp(prefix="template_diff_")
        logger.info(f"Created temporary directory: {self.temp_dir}")

    async def process(self, request, event_sender):
        """
        Process the agent request and generate a counter application.

        Args:
            request: The agent request containing messages and context
            event_sender: Channel to send events back to the client
        """
        try:
            logger.info(f"Processing request for application {self.application_id}, trace {self.trace_id}")

            user_message = request.all_messages[-1].content if request.all_messages else "Create a counter app"

            await event_sender.send(AgentSseEvent(
                status=AgentStatus.RUNNING,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="assistant",
                    kind=MessageKind.STAGE_RESULT,
                    content="Starting counter app generation...",
                    agentState=self.state,
                    unifiedDiff=None
                )
            ))

            server_files, frontend_files, unified_diff = self._generate_counter_app(user_message)

            self._save_files(server_files, frontend_files)

            self.state = {
                "app_type": "counter",
                "files_generated": len(server_files) + len(frontend_files),
                "server_files": list(server_files.keys()),
                "frontend_files": list(frontend_files.keys()),
                "temp_dir": self.temp_dir
            }

            await event_sender.send(AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="assistant",
                    kind=MessageKind.REVIEW_RESULT,
                    content=f"Counter application generated successfully with {len(server_files)} server files and {len(frontend_files)} frontend files.",
                    agentState=self.state,
                    unifiedDiff=unified_diff
                )
            ))

        except Exception as e:
            logger.exception(f"Error processing request: {str(e)}")

            await event_sender.send(AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="assistant",
                    kind=MessageKind.RUNTIME_ERROR,
                    content=f"Error generating counter application: {str(e)}",
                    agentState=self.state,
                    unifiedDiff=None
                )
            ))

        finally:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            await event_sender.aclose()


    def _generate_counter_app(self, user_message: str) -> Tuple[Dict[str, str], Dict[str, str], str]:
        """
        Generate a counter application based on the user message.

        Args:
            user_message: The user's request message

        Returns:
            Tuple containing server files, frontend files, and unified diff
        """
        logger.info(f"Generating counter app based on: {user_message}")

        # Use the pre-defined counter_app.patch file
        patch_file_path = os.path.join(os.path.dirname(__file__), "counter_app.patch")

        with open(patch_file_path, 'r') as f:
            unified_diff = f.read()

        # Extract files from the patch
        server_files = {}
        frontend_files = {}

        # Parse the patch to extract file contents
        current_file = None
        current_content = []
        file_path = None

        for line in unified_diff.split('\n'):
            # Check for new file headers
            if line.startswith('diff --git'):
                # Save previous file if exists
                if current_file and file_path:
                    content = '\n'.join(current_content)
                    if file_path.startswith('server/'):
                        server_files[os.path.basename(file_path)] = content
                    elif file_path.startswith('frontend/'):
                        frontend_files[os.path.basename(file_path)] = content

                # Reset for new file
                current_file = line
                current_content = []
                file_path = None

            # Extract file path from +++ line
            elif line.startswith('+++') and not line.startswith('+++ /dev/null'):
                file_path = line.split(' ')[1][2:]  # Remove "b/" prefix

            # Collect content lines (those starting with +)
            elif line.startswith('+') and not line.startswith('+++'):
                current_content.append(line[1:])  # Remove the + sign

        # Don't forget the last file
        if current_file and file_path:
            content = '\n'.join(current_content)
            if file_path.startswith('server/'):
                server_files[os.path.basename(file_path)] = content
            elif file_path.startswith('frontend/'):
                frontend_files[os.path.basename(file_path)] = content

        return server_files, frontend_files, unified_diff

    def _save_files(self, server_files: Dict[str, str], frontend_files: Dict[str, str]) -> None:
        """
        Save the generated files to the temporary directory.

        Args:
            server_files: Dictionary of server file names to content
            frontend_files: Dictionary of frontend file names to content
        """
        server_dir = os.path.join(self.temp_dir, "server")
        os.makedirs(server_dir, exist_ok=True)

        for filename, content in server_files.items():
            file_path = os.path.join(server_dir, filename)
            with open(file_path, "w") as f:
                f.write(content)
            logger.info(f"Saved server file: {file_path}")

        frontend_dir = os.path.join(self.temp_dir, "frontend")
        os.makedirs(frontend_dir, exist_ok=True)

        for filename, content in frontend_files.items():
            file_path = os.path.join(frontend_dir, filename)
            with open(file_path, "w") as f:
                f.write(content)
            logger.info(f"Saved frontend file: {file_path}")

        metadata = {
            "server_files": list(server_files.keys()),
            "frontend_files": list(frontend_files.keys()),
            "timestamp": os.path.getmtime(self.temp_dir)
        }

        metadata_path = os.path.join(self.temp_dir, "metadata.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Saved metadata: {metadata_path}")
