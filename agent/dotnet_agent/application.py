import os
import anyio
import logging
import enum
from typing import Dict, Self, Optional, Literal, Any
from dataclasses import dataclass, field
from core.statemachine import StateMachine, State, Context
from llm.utils import get_llm_client
from core.actors import BaseData
from core.base_node import Node
from core.statemachine import MachineCheckpoint
from core.workspace import Workspace
from trpc_agent.diff_edit_actor import EditActor
from dotnet_agent.actors import DotNetDraftActor, DotNetHandlersActor, DotNetFrontendActor, DotNetConcurrentActor
import dagger

# Set up logging
logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)
for package in ['urllib3', 'httpx', 'google_genai.models']:
    logging.getLogger(package).setLevel(logging.WARNING)


class FSMState(str, enum.Enum):
    DRAFT = "draft"
    REVIEW_DRAFT = "review_draft"
    APPLICATION = "application"
    REVIEW_APPLICATION = "review_application"
    APPLY_FEEDBACK = "apply_feedback"
    COMPLETE = "complete"
    FAILURE = "failure"


@dataclass(frozen=True) # Use dataclass for easier serialization, frozen=True makes it hashable by default if needed
class FSMEvent:
    type_: Literal["CONFIRM", "FEEDBACK"]
    feedback: Optional[str] = None

    def __eq__(self, other):
        match other:
            case FSMEvent():
                return self.type_ == other.type_
            case str():
                return self.type_ == other
            case _:
                raise TypeError(f"Cannot compare FSMEvent with {type(other)}")

    def __hash__(self):
        return hash(self.type_)

    def __str__(self):
        return self.type_


@dataclass
class ApplicationContext(Context):
    """Context for the .NET application state machine"""
    user_prompt: str
    feedback_data: Optional[str] = None
    files: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None

    def dump(self) -> dict:
        """Dump context to a serializable dictionary"""
        # Convert dataclass to dictionary
        data = {
            "user_prompt": self.user_prompt,
            "feedback_data":self.feedback_data,
            "files": self.files,
            "error": self.error
        }
        return data

    @classmethod
    def load(cls, data: object) -> Self:
        """Load context from a serializable dictionary"""
        if not isinstance(data, dict):
            raise ValueError(f"Invalid data type: {type(data)}")
        return cls(**data)


class DotNetFSMApplication:

    def __init__(self, client: dagger.Client, fsm: StateMachine[ApplicationContext, FSMEvent]):
        self.fsm = fsm
        self.client = client

    @classmethod
    async def load(cls, client: dagger.Client, data: MachineCheckpoint) -> Self:
        root = await cls.make_states(client)
        fsm = await StateMachine[ApplicationContext, FSMEvent].load(root, data, ApplicationContext)
        return cls(client, fsm)

    @classmethod
    def base_execution_plan(cls) -> str:
        return "\n".join([
            "1. Application draft. Contains models, DTOs, Entity Framework DbContext and controller declarations only.",
            "2. Core backend implementations with Entity Framework operations and React frontend.",
            "",
            "The result application will be based on .NET 8, ASP.NET Core Web API, Entity Framework Core, PostgreSQL, and React with TypeScript."
        ])

    @classmethod
    async def start_fsm(cls, client: dagger.Client, user_prompt: str, settings: Dict[str, Any] | None = None) -> Self:
        """Create the state machine for the .NET application"""
        states = await cls.make_states(client, settings)
        context = ApplicationContext(user_prompt=user_prompt)
        fsm = StateMachine[ApplicationContext, FSMEvent](states, context)
        await fsm.send(FSMEvent("CONFIRM")) # confirm running first stage immediately
        return cls(client, fsm)

    @classmethod
    async def make_states(cls, client: dagger.Client, settings: Dict[str, Any] | None = None) -> State[ApplicationContext, FSMEvent]:
        def agg_node_files(solution: Node[BaseData]) -> dict[str, str]:
            files = {}
            for node in solution.get_trajectory():
                files.update(node.data.files)
            return files

        # Define actions to update context
        async def update_node_files(ctx: ApplicationContext, result: Node[BaseData] | Dict[str, Node[BaseData]]) -> None:
            logger.info("Updating context files from result")
            if isinstance(result, Node):
                ctx.files.update(agg_node_files(result))
            elif isinstance(result, dict):
                for key, node in result.items():
                    ctx.files.update(agg_node_files(node))

        async def set_error(ctx: ApplicationContext, error: Exception) -> None:
            """Set error in context"""
            # Use logger.exception to include traceback
            logger.exception("Setting error in context:", exc_info=error)
            ctx.error = str(error)

        llm = get_llm_client()
        vlm = get_llm_client(model_name="gemini-flash-lite")
        model_params = settings or {}
        
        workspace = await Workspace.create(
            client=client,
            base_image="mcr.microsoft.com/dotnet/sdk:8.0",
            context=client.host().directory("./dotnet_agent/template"),
            setup_cmd=[["dotnet", "restore", "server"]],
        )

        draft_actor = DotNetDraftActor(llm, workspace.clone(), model_params)
        application_actor = DotNetConcurrentActor(
            handlers=DotNetHandlersActor(llm, workspace.clone(), model_params, beam_width=3),
            frontend=DotNetFrontendActor(llm, vlm, workspace.clone(), model_params, beam_width=1, max_depth=20)
        )
        edit_actor = EditActor(llm, vlm, workspace.clone())

        # Define state machine states
        states = State[ApplicationContext, FSMEvent](
            on={
                FSMEvent("CONFIRM"): FSMState.DRAFT,
                FSMEvent("FEEDBACK"): FSMState.APPLY_FEEDBACK,
            },
            states={
                FSMState.DRAFT: State(
                    invoke={
                        "src": draft_actor,
                        "input_fn": lambda ctx: (ctx.feedback_data or ctx.user_prompt,),
                        "on_done": {
                            "target": FSMState.REVIEW_DRAFT,
                            "actions": [update_node_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.REVIEW_DRAFT: State(
                    on={
                        FSMEvent("CONFIRM"): FSMState.APPLICATION,
                        FSMEvent("FEEDBACK"): FSMState.DRAFT,
                    },
                ),
                FSMState.APPLICATION: State(
                    invoke={
                        "src": application_actor,
                        "input_fn": lambda ctx: (ctx.user_prompt, ctx.files, ctx.feedback_data),
                        "on_done": {
                            "target": FSMState.REVIEW_APPLICATION,
                            "actions": [update_node_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.REVIEW_APPLICATION: State(
                    on={
                        FSMEvent("CONFIRM"): FSMState.COMPLETE,
                        FSMEvent("FEEDBACK"): FSMState.APPLY_FEEDBACK,
                    },
                ),
                FSMState.APPLY_FEEDBACK: State(
                    invoke={
                        "src": edit_actor,
                        "input_fn": lambda ctx: (ctx.files, ctx.user_prompt, ctx.feedback_data),
                        "on_done": {
                            "target": FSMState.COMPLETE,
                            "actions": [update_node_files]
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    }
                ),
                FSMState.COMPLETE: State(),
                FSMState.FAILURE: State(),
            },
        )

        return states

    async def confirm_state(self):
        await self.fsm.send(FSMEvent("CONFIRM"))

    async def apply_changes(self, feedback: str):
        self.fsm.context.feedback_data = feedback
        await self.fsm.send(FSMEvent("FEEDBACK"))

    async def complete_fsm(self):
        while (self.current_state not in (FSMState.COMPLETE, FSMState.FAILURE)):
            await self.fsm.send(FSMEvent("CONFIRM"))

    @property
    def is_completed(self) -> bool:
        return self.current_state == FSMState.COMPLETE or self.current_state == FSMState.FAILURE

    def maybe_error(self) -> str | None:
        return self.fsm.context.error

    @property
    def current_state(self) -> str:
        if self.fsm.stack_path:
            return self.fsm.stack_path[-1]
        return ""

    @property
    def truncated_files(self) -> dict[str, str]:
        return {k: "large file truncated" if len(v) > 256 else v for k, v in self.fsm.context.files.items()}

    @property
    def state_output(self) -> dict:
        match self.current_state:
            case FSMState.REVIEW_DRAFT:
                return {"draft": self.fsm.context.files}
            case FSMState.REVIEW_APPLICATION:
                return {"application": self.truncated_files}
            case FSMState.COMPLETE:
                return {"application": self.fsm.context.files}
            case FSMState.FAILURE:
                return {"error": self.fsm.context.error or "Unknown error"}
            case _:
                logger.debug(f"State {self.current_state} is a processing state, returning processing status")
                return {"status": "processing"}

    @property
    def available_actions(self) -> dict[str, str]:
        actions = {}
        match self.current_state:
            case FSMState.REVIEW_DRAFT | FSMState.REVIEW_APPLICATION:
                actions = {"confirm": "Accept current output and continue"}
                logger.debug(f"Review state detected: {self.current_state}, offering confirm action")
            case FSMState.COMPLETE:
                actions = {
                    "complete": "Finalize and get all artifacts",
                    "change": "Submit feedback for the current FSM state and trigger revision",
                }
                logger.debug("FSM is in COMPLETE state, offering complete action")
            case FSMState.FAILURE:
                actions = {"get_error": "Get error details"}
                logger.debug("FSM is in FAILURE state, offering get_error action")
            case _:
                actions = {"wait": "Wait for processing to complete"}
                logger.debug(f"FSM is in processing state: {self.current_state}, offering wait action")
        return actions

    async def get_diff_with(self, snapshot: dict[str, str]) -> str:
        logger.info(f"SERVER get_diff_with: Received snapshot with {len(snapshot)} files.")
        if snapshot:
            # Sort keys for consistent sample logging, especially in tests
            sorted_snapshot_keys = sorted(snapshot.keys())
            logger.info(f"SERVER get_diff_with: Snapshot sample paths (up to 5): {sorted_snapshot_keys[:5]}")
            if len(snapshot) > 5:
                logger.debug(f"SERVER get_diff_with: All snapshot paths: {sorted_snapshot_keys}")
        else:
            logger.info("SERVER get_diff_with: Snapshot is empty. Diff will be against template + FSM context files.")

        logger.debug("SERVER get_diff_with: Initializing Dagger context from empty directory")
        context = self.client.directory()

        gitignore_path = "./dotnet_agent/template/.gitignore"
        try:
            gitignore_file = self.client.host().file(gitignore_path)
            context = context.with_file(".gitignore", gitignore_file)
            logger.info(f"SERVER get_diff_with: Added .gitignore from {gitignore_path} to Dagger context.")
        except Exception as e:
            logger.warning(f"SERVER get_diff_with: Could not load/add .gitignore from {gitignore_path}: {e}. Proceeding without.")

        logger.info(f"SERVER get_diff_with: Writing {len(snapshot)} files from received snapshot to Dagger context.")
        for key, value in snapshot.items():
            logger.debug(f"SERVER get_diff_with:  Adding snapshot file to Dagger context: {key}")
            context = context.with_new_file(key, value)

        logger.info("SERVER get_diff_with: Creating Dagger workspace for diff generation.")
        workspace = await Workspace.create(self.client, base_image="alpine/git", context=context)
        logger.debug("SERVER get_diff_with: Dagger workspace created with initial snapshot context.")

        template_dir_path = "./dotnet_agent/template"
        try:
            template_dir = self.client.host().directory(template_dir_path)
            workspace.ctr = workspace.ctr.with_directory(".", template_dir)
            logger.info(f"SERVER get_diff_with: Template directory {template_dir_path} merged into Dagger workspace root.")
        except Exception as e:
            logger.error(f"SERVER get_diff_with: FAILED to merge template directory {template_dir_path} into workspace: {e}")

        fsm_files_count = len(self.fsm.context.files)
        logger.info(f"SERVER get_diff_with: Writing {fsm_files_count} files from FSM context to Dagger workspace (overlaying snapshot & template).")
        if fsm_files_count > 0:
             logger.debug(f"SERVER get_diff_with: FSM files (sample): {list(self.fsm.context.files.keys())[:5]}")
        for key, value in self.fsm.context.files.items():
            logger.debug(f"SERVER get_diff_with:  Writing FSM file to Dagger workspace: {key} (Length: {len(value)})")
            try:
                workspace.write_file(key, value)
            except Exception as e:
                logger.error(f"SERVER get_diff_with: FAILED to write FSM file {key} to workspace: {e}")

        logger.info("SERVER get_diff_with: Calling workspace.diff() to generate final diff.")
        final_diff_output = ""
        try:
            final_diff_output = await workspace.diff()
            logger.info(f"SERVER get_diff_with: workspace.diff() Succeeded. Diff length: {len(final_diff_output)}")
            if not final_diff_output:
                 logger.warning("SERVER get_diff_with: Diff output is EMPTY. This might be expected if states match or an issue.")
        except Exception as e:
            logger.exception("SERVER get_diff_with: Error during workspace.diff() execution.")
            final_diff_output = f"# ERROR GENERATING DIFF: {e}"

        return final_diff_output


async def main(user_prompt="Minimal product management application"):
    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        fsm_app: DotNetFSMApplication = await DotNetFSMApplication.start_fsm(client, user_prompt)

        while (fsm_app.current_state not in (FSMState.COMPLETE, FSMState.FAILURE)):
            await fsm_app.fsm.send(FSMEvent("CONFIRM"))

        context = fsm_app.fsm.context
        if fsm_app.maybe_error():
            logger.error(f"Application run failed: {context.error or 'Unknown error'}")
        else:
            logger.info("Application run completed successfully")
            logger.info(f"Generated {len(context.files)} files")
            logger.info("Applying edit to application.")
            await fsm_app.apply_changes("Add header that says 'Welcome to Product Management'")

            if fsm_app.maybe_error():
                logger.error(f"Failed to apply edit: {context.error or 'Unknown error'}")
            else:
                logger.info("Edit applied successfully")


if __name__ == "__main__":
    anyio.run(main)