import logging
from abc import ABC
from typing import Dict, Any, Optional, TypedDict, List, Union, Type
from datetime import datetime
from uuid import uuid4
import dagger

from anyio.streams.memory import MemoryObjectSendStream

from llm.common import ContentBlock, InternalMessage, TextRaw
from llm.utils import get_ultra_fast_llm_client, get_universal_llm_client
from api.fsm_tools import FSMToolProcessor, FSMStatus, FSMInterface
from api.snapshot_utils import snapshot_saver
from core.statemachine import MachineCheckpoint

from api.agent_server.models import (
    AgentRequest,
    AgentSseEvent,
    AgentMessage,
    ConversationMessage,
    UserMessage,
    AgentStatus,
    ExternalContentBlock,
    MessageKind,
    format_internal_message_for_display,
)
from api.agent_server.interface import AgentInterface
from llm.llm_generators import generate_app_name, generate_commit_message

logger = logging.getLogger(__name__)


class StateMetadata(TypedDict):
    app_name: str | None
    template_diff_sent: bool


class AgentState(TypedDict):
    fsm_state: MachineCheckpoint | None
    fsm_messages: List[InternalMessage]
    metadata: StateMetadata


class BaseAgentSession(AgentInterface, ABC):
    """Base class for agent sessions with common functionality"""

    def __init__(self, client: dagger.Client, fsm_application_class: Type[FSMInterface], application_id: str | None = None, trace_id: str | None = None, settings: Optional[Dict[str, Any]] = None):
        """Initialize a new agent session"""
        self.application_id = application_id or uuid4().hex
        self.trace_id = trace_id or uuid4().hex
        self.settings = settings or {}
        self.fsm_application_class = fsm_application_class
        self.processor_instance = None  # type: Optional[FSMToolProcessor]
        # ^ always initialized in process method
        self.model_params = {
            "max_tokens": 8192,
        }
        self.client = client
        self._sse_counter = 0
        self._snapshot_key = self.trace_id + "_" + datetime.now().strftime("%m%d%H%M%S")

    @property
    def template_path(self) -> str:
        """Get the template path for this agent session."""
        return self.fsm_application_class.template_path()

    @staticmethod
    def convert_agent_messages_to_llm_messages(saved_messages: List[ConversationMessage | InternalMessage]) -> List[InternalMessage]:
        """Convert ConversationMessage list to LLM InternalMessage format."""
        internal_messages: List[InternalMessage] = []
        for m in saved_messages:
            if isinstance(m, UserMessage):
                internal_messages.append(
                    InternalMessage(
                        role=m.role,
                        content=[TextRaw(text=m.content)]
                    )
                )
            elif isinstance(m, AgentMessage):
                blocks: List[ContentBlock] = []
                for block in m.messages or []:
                    blocks.append(TextRaw(text=block.content))
                internal_messages.append(
                    InternalMessage(
                        role=m.role,
                        content=blocks
                    )
                )
            else:
                raise ValueError(f"Unsupported message type: {type(m)}")

        return internal_messages

    @staticmethod
    def prepare_snapshot_from_request(request: AgentRequest) -> Dict[str, str]:
        """Prepare snapshot files from request.all_files."""
        snapshot_files = {}
        if request.all_files:
            for file_entry in request.all_files:
                snapshot_files[file_entry.path] = file_entry.content
        return snapshot_files

    async def process(self, request: AgentRequest, event_tx: MemoryObjectSendStream[AgentSseEvent]) -> None:
        """
        Process the incoming request and send events to the event stream.
        This is the main method required by the AgentInterface protocol.

        Args:
            request: Incoming agent request
            event_tx: Event transmission stream
        """
        try:
            logger.info(f"Processing request for {self.application_id}:{self.trace_id}")

            # build always valid blank state
            fsm_app = None
            fsm_state: MachineCheckpoint | None = None
            fsm_message_history = self.convert_agent_messages_to_llm_messages(request.all_messages[-1:])
            metadata: StateMetadata = {
                "app_name": None,
                "template_diff_sent": False,
            }

            async def emit_intermediate_message(message: str) -> None:
                logger.info(f"Emitting intermediate message: {message}")
                await self.send_event(
                    event_tx=event_tx,
                    status=AgentStatus.RUNNING,
                    kind=MessageKind.WIP_UPDATE,
                    content=message,
                    agent_state=None,
                    unified_diff=None,
                    app_name=metadata["app_name"],
                )

            fsm_settings = {**self.settings, 'event_callback': emit_intermediate_message}

            if request.agent_state:
                logger.info(f"Continuing with existing state for trace {self.trace_id}")
                if (fsm_messages := request.agent_state.get("fsm_messages", [])):
                    fsm_message_history = [InternalMessage.from_dict(m) for m in fsm_messages] + fsm_message_history
                if (req_fsm_state := request.agent_state.get("fsm_state")):
                    fsm_state = req_fsm_state
                    if request.all_files:
                        fsm_state["context"]["files"].update({p.path: p.content for p in request.all_files})  # pyright: ignore
                    fsm_app = await self.fsm_application_class.load(self.client, req_fsm_state, fsm_settings)
                    snapshot_saver.save_snapshot(trace_id=self._snapshot_key, key="fsm_enter", data=req_fsm_state)
                if (req_metadata := request.agent_state.get("metadata")):
                    metadata.update(req_metadata)
            else:
                logger.info(f"Initializing new session for trace {self.trace_id}")

            # Unconditional initialization with event callback
            self.processor_instance = FSMToolProcessor(self.client, self.fsm_application_class, fsm_app=fsm_app, settings=fsm_settings, event_callback=emit_intermediate_message)
            agent_state: AgentState = {
                "fsm_messages": fsm_message_history,
                "fsm_state": fsm_state,
                "metadata": metadata,
            }
            snapshot_files = {**fsm_state["context"]["files"]} if fsm_state else {}  # pyright: ignore

            # Processing
            logger.info(f"Last user message: {fsm_message_history[-1].content}")

            lite_client = get_ultra_fast_llm_client()
            top_level_agent_llm = get_universal_llm_client()

            while True:
                logger.info("Looping into next step")
                thread, fsm_status, full_thread = await self.processor_instance.step(
                    agent_state["fsm_messages"],
                    top_level_agent_llm,
                    self.model_params
                )

                # Add messages for agentic loop
                agent_state["fsm_messages"] = full_thread

                if self.processor_instance.fsm_app is not None:
                    logger.info("Saving FSM state")
                    agent_state["fsm_state"] = await self.processor_instance.fsm_app.fsm.dump()

                if not agent_state["metadata"]["template_diff_sent"] and self.processor_instance.fsm_app is not None:
                    prompt = self.processor_instance.fsm_app.fsm.context.user_prompt
                    app_name = await generate_app_name(prompt, lite_client)
                    await self.send_event(
                        event_tx=event_tx,
                        status=AgentStatus.RUNNING,
                        kind=MessageKind.STAGE_RESULT,
                        content="Initializing application...",
                        agent_state=None,
                        unified_diff=None,
                        app_name=app_name
                    )

                    logger.info("Getting initial template diff")

                    # Communicate the app name and commit message and template diff to the client
                    initial_template_diff = await self.processor_instance.fsm_app.get_diff_with({})

                    logger.info("Sending initial template diff")
                    agent_state["metadata"].update({"app_name": app_name, "template_diff_sent": True})
                    await self.send_event(
                        event_tx=event_tx,
                        status=AgentStatus.RUNNING,
                        kind=MessageKind.REVIEW_RESULT,
                        content="Application initialized",
                        agent_state=None,
                        unified_diff=initial_template_diff,
                        app_name=app_name,
                        commit_message="Initial commit"
                    )

                # Send event based on FSM status
                match fsm_status:
                    case FSMStatus.WIP:
                        logger.info("Got WIP status, skipping sending event due to callback messages were already sent")
                        continue
                    case FSMStatus.REFINEMENT_REQUEST:
                        logger.info("Got REFINEMENT_REQUEST status, sending refinement request message")
                        # Use the actual LLM response from thread if available
                        messages_to_send = thread if thread else [InternalMessage(
                            role="assistant",
                            content=[TextRaw("Agent is waiting for user input...")]
                        )]
                        await self.send_event(
                            event_tx=event_tx,
                            status=AgentStatus.IDLE,
                            kind=MessageKind.REFINEMENT_REQUEST,
                            content=messages_to_send,
                            agent_state=agent_state,
                            app_name=agent_state["metadata"]["app_name"],
                        )
                    case FSMStatus.FAILED:
                        logger.info("Got FAILED status, sending runtime error message")
                        runtime_error_message = InternalMessage(
                                    role="assistant",
                                    content=[TextRaw("Runtime error occurred, please try again. If the problem persists, please create an issue on GitHub.")]
                                )
                        await self.send_event(
                            event_tx=event_tx,
                            status=AgentStatus.IDLE,
                            kind=MessageKind.RUNTIME_ERROR,
                            content=[runtime_error_message],
                        )
                    case FSMStatus.COMPLETED:
                        try:
                            assert self.processor_instance.fsm_app is not None
                            logger.info("FSM is completed")

                            final_diff = await self.processor_instance.fsm_app.get_diff_with(snapshot_files)

                            logger.info(
                                "Sending completion event with diff (length: %d) for state %s",
                                len(final_diff) if final_diff else 0,
                                self.processor_instance.fsm_app.current_state,
                            )

                            is_diff_meaningful = final_diff and final_diff.strip()

                            # Check if diff is ready
                            if not is_diff_meaningful:
                                logger.info("No meaningful changes detected, sending work successful without diff")

                                no_changes_message = InternalMessage(
                                    role="assistant",
                                    content=[TextRaw("No changes were generated by the agent. Please refine your request.")]
                                )

                                await self.send_event(
                                    event_tx=event_tx,
                                    status=AgentStatus.IDLE,
                                    kind=MessageKind.STAGE_RESULT,
                                    content=[no_changes_message],
                                    agent_state=agent_state,
                                    app_name=agent_state["metadata"]["app_name"],
                                )
                            else:
                                logger.info("Got COMPLETED status, sending final diff")
                                # The message with the messages already sent in the callback,
                                # so we don't need to send it again

                                if isinstance(request.all_messages[-1], UserMessage):
                                    user_request = request.all_messages[-1].content
                                else:
                                    user_request = self.processor_instance.fsm_app.fsm.context.user_prompt

                                commit_message = await generate_commit_message(user_request, lite_client)

                                # Send actual diff in a separate event
                                await self.send_event(
                                    event_tx=event_tx,
                                    status=AgentStatus.IDLE,
                                    kind=MessageKind.REVIEW_RESULT,
                                    content=f"Changes generated: \n{commit_message}",
                                    agent_state=agent_state,
                                    unified_diff=final_diff,
                                    app_name=agent_state["metadata"]["app_name"],
                                    commit_message=commit_message
                                )
                        except Exception as e:
                            logger.exception(f"Error sending final diff: {e}")

                # Exit if we are not working on a FSM or if the FSM is completed or failed
                if fsm_status != FSMStatus.WIP:
                    break

        except Exception as e:
            logger.exception(f"Error in process: {str(e)}")
            await self.send_event(
                event_tx=event_tx,
                status=AgentStatus.IDLE,
                kind=MessageKind.RUNTIME_ERROR,
                content=f"Error processing request: {str(e)}"
            )
        finally:
            if self.processor_instance.fsm_app is not None:
                snapshot_saver.save_snapshot(
                    trace_id=self._snapshot_key,
                    key="fsm_exit",
                    data=await self.processor_instance.fsm_app.fsm.dump(),
                )
            await event_tx.aclose()

    # ---------------------------------------------------------------------
    # Event sending helpers
    # ---------------------------------------------------------------------
    async def send_event(
        self,
        event_tx: MemoryObjectSendStream[AgentSseEvent],
        status: AgentStatus,
        kind: MessageKind,
        content: Union[List[InternalMessage], str],
        agent_state: Optional[AgentState] = None,
        unified_diff: Optional[str] = None,
        app_name: Optional[str] = None,
        commit_message: Optional[str] = None,
    ) -> None:
        """Send event with specified parameters."""
        structured_blocks: List[ExternalContentBlock]
        if isinstance(content, list):
            structured_blocks = [
                ExternalContentBlock(
                    content=format_internal_message_for_display(x),
                    #timestamp=datetime.datetime.now(datetime.UTC)
                )
                for x in content
            ]
        else:
            structured_blocks = [
                ExternalContentBlock(
                    content=content,
                    #timestamp=datetime.datetime.now(datetime.UTC)
                )
            ]


        event = AgentSseEvent(
            status=status,
            traceId=self.trace_id,
            message=AgentMessage(
                role="assistant",
                kind=kind,
                messages=structured_blocks,
                agentState={
                    "fsm_state": agent_state["fsm_state"],
                    "fsm_messages": [x.to_dict() for x in agent_state["fsm_messages"]],
                    "metadata": agent_state["metadata"],
                } if agent_state else None,
                unifiedDiff=unified_diff,
                complete_diff_hash=None,
                diff_stat=None,
                app_name=app_name,
                commit_message=commit_message
            )
        )
        await event_tx.send(event)
        snapshot_saver.save_snapshot(
            trace_id=self._snapshot_key,
            key=f"sse_events/{self._sse_counter}",
            data=event.model_dump(),
        )
        self._sse_counter += 1
