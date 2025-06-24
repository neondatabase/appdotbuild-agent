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
from nicegui_agent.actors import NiceguiActor
import dagger

# Set up logging
logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)
for package in ["urllib3", "httpx", "google_genai.models"]:
    logging.getLogger(package).setLevel(logging.WARNING)


class FSMState(str, enum.Enum):
    APPLICATION = "application"
    REVIEW_APPLICATION = "review_application"
    APPLY_FEEDBACK = "apply_feedback"
    COMPLETE = "complete"
    FAILURE = "failure"


@dataclass(
    frozen=True
)  # Use dataclass for easier serialization, frozen=True makes it hashable by default if needed
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
    """Context for the fullstack application state machine"""

    user_prompt: str
    feedback_data: Optional[str] = None
    files: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None

    def dump(self) -> dict:
        """Dump context to a serializable dictionary"""
        # Convert dataclass to dictionary
        data = {
            "user_prompt": self.user_prompt,
            "feedback_data": self.feedback_data,
            "files": self.files,
            "error": self.error,
        }
        return data

    @classmethod
    def load(cls, data: object) -> Self:
        """Load context from a serializable dictionary"""
        if not isinstance(data, dict):
            raise ValueError(f"Invalid data type: {type(data)}")
        return cls(**data)


class FSMApplication:
    def __init__(
        self, client: dagger.Client, fsm: StateMachine[ApplicationContext, FSMEvent]
    ):
        self.fsm = fsm
        self.client = client

    @classmethod
    async def load(
        cls,
        client: dagger.Client,
        data: MachineCheckpoint,
        settings: Dict[str, Any] | None = None,
    ) -> Self:
        root = await cls.make_states(client, settings)
        fsm = await StateMachine[ApplicationContext, FSMEvent].load(
            root, data, ApplicationContext
        )
        return cls(client, fsm)

    @classmethod
    def base_execution_plan(cls) -> str:
        return "\n".join(
            [
                "1. NiceGUI application development based on user requirements.",
                "",
                "The result application will be based on Python and NiceGUI framework. The application can include various UI components, event handling, and state management.",
            ]
        )

    @classmethod
    def template_path(cls) -> str:
        return "./nicegui_agent/template"

    @classmethod
    async def start_fsm(
        cls,
        client: dagger.Client,
        user_prompt: str,
        settings: Dict[str, Any] | None = None,
    ) -> Self:
        """Create the state machine for the application"""
        states = await cls.make_states(client, settings)
        context = ApplicationContext(user_prompt=user_prompt)
        fsm = StateMachine[ApplicationContext, FSMEvent](states, context)
        await fsm.send(FSMEvent("CONFIRM"))  # confirm running first stage immediately
        return cls(client, fsm)

    @classmethod
    async def make_states(
        cls, client: dagger.Client, settings: Dict[str, Any] | None = None
    ) -> State[ApplicationContext, FSMEvent]:
        # Define actions to update context
        async def update_node_files(
            ctx: ApplicationContext, result: Node[BaseData]
        ) -> None:
            logger.info("Updating context files from result")
            files = {}
            for node in result.get_trajectory():
                files.update(node.data.files)
            ctx.files.update({k: v for k, v in files.items() if v is not None})

        async def set_error(ctx: ApplicationContext, error: Exception) -> None:
            """Set error in context"""
            # Use logger.exception to include traceback
            logger.exception("Setting error in context:", exc_info=error)
            ctx.error = str(error)

        llm = get_llm_client()
        workspace = await Workspace.create(
            client=client,
            base_image="alpine:3.21.3",
            context=client.host().directory("./nicegui_agent/template"),
            setup_cmd=[
                ["apk", "add", "--update", "--no-cache", "curl", "python3"],
                [
                    "sh",
                    "-c",
                    "curl -LsSf https://astral.sh/uv/install.sh | XDG_BIN_HOME=/usr/local/bin sh",
                ],
                ["uv", "sync"],
            ],
        )

        nicegui_actor = NiceguiActor(
            llm=llm,
            workspace=workspace,
            beam_width=1,
        )

        # Define state machine states
        states = State[ApplicationContext, FSMEvent](
            on={
                FSMEvent("CONFIRM"): FSMState.APPLICATION,
                FSMEvent("FEEDBACK"): FSMState.APPLY_FEEDBACK,
            },
            states={
                FSMState.APPLICATION: State(
                    invoke={
                        "src": nicegui_actor,
                        "input_fn": lambda ctx: (
                            ctx.files,
                            ctx.feedback_data or ctx.user_prompt,
                        ),
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
                        "src": nicegui_actor,
                        "input_fn": lambda ctx: (
                            ctx.files,
                            ctx.feedback_data,
                        ),
                        "on_done": {
                            "target": FSMState.COMPLETE,
                            "actions": [update_node_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
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
        while self.current_state not in (FSMState.COMPLETE, FSMState.FAILURE):
            await self.fsm.send(FSMEvent("CONFIRM"))

    @property
    def is_completed(self) -> bool:
        return (
            self.current_state == FSMState.COMPLETE
            or self.current_state == FSMState.FAILURE
        )

    def maybe_error(self) -> str | None:
        return self.fsm.context.error

    @property
    def current_state(self) -> str:
        if self.fsm.stack_path:
            return self.fsm.stack_path[-1]
        return ""

    @property
    def truncated_files(self) -> dict[str, str]:
        return {
            k: "large file truncated" if len(v) > 256 else v
            for k, v in self.fsm.context.files.items()
        }

    @property
    def state_output(self) -> dict:
        match self.current_state:
            case FSMState.REVIEW_APPLICATION:
                return {"application": self.truncated_files}
            case FSMState.COMPLETE:
                return {"application": self.fsm.context.files}
            case FSMState.FAILURE:
                return {"error": self.fsm.context.error or "Unknown error"}
            case _:
                logger.debug(
                    f"State {self.current_state} is a processing state, returning processing status"
                )
                return {"status": "processing"}

    @property
    def available_actions(self) -> dict[str, str]:
        actions = {}
        match self.current_state:
            case FSMState.REVIEW_APPLICATION:
                actions = {"confirm": "Accept current output and continue"}
                logger.debug(
                    f"Review state detected: {self.current_state}, offering confirm action"
                )
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
                logger.debug(
                    f"FSM is in processing state: {self.current_state}, offering wait action"
                )
        return actions

    async def get_diff_with(self, snapshot: dict[str, str]) -> str:
        logger.info(
            f"SERVER get_diff_with: Received snapshot with {len(snapshot)} files."
        )

        # Start with empty directory and git init
        start = self.client.container().from_("alpine/git").with_workdir("/app")
        start = start.with_exec(["git", "init"]).with_exec(
            ["git", "config", "--global", "user.email", "agent@appbuild.com"]
        )
        if snapshot:
            # Sort keys for consistent sample logging, especially in tests
            sorted_snapshot_keys = sorted(snapshot.keys())
            logger.info(
                f"SERVER get_diff_with: Snapshot sample paths (up to 5): {sorted_snapshot_keys[:5]}"
            )
            for file_path, content in snapshot.items():
                start = start.with_new_file(file_path, content)
            start = start.with_exec(["git", "add", "."]).with_exec(
                ["git", "commit", "-m", "'snapshot'"]
            )
        else:
            logger.info(
                "SERVER get_diff_with: Snapshot is empty. Diff will be against template + FSM context files."
            )
            # If no snapshot, create an empty initial commit
            start = (
                start.with_exec(["touch", "README.md"])
                .with_exec(["git", "add", "."])
                .with_exec(["git", "commit", "-m", "'initial'"])
            )

        # Add template files (they will appear in diff if not in snapshot)
        template_dir = self.client.host().directory("./nicegui_agent/template")
        start = start.with_directory(".", template_dir)
        logger.info("SERVER get_diff_with: Added template directory to workspace")

        # Add FSM context files on top
        for file_path, content in self.fsm.context.files.items():
            start = start.with_new_file(file_path, content)

        logger.info(
            "SERVER get_diff_with: Calling workspace.diff() to generate final diff."
        )
        diff = ""
        try:
            diff = (
                await start.with_exec(["git", "add", "."])
                .with_exec(["git", "diff", "HEAD"])
                .stdout()
            )
            logger.info(
                f"SERVER get_diff_with: workspace.diff() Succeeded. Diff length: {len(diff)}"
            )
            if not diff:
                logger.warning(
                    "SERVER get_diff_with: Diff output is EMPTY. This might be expected if states match or an issue."
                )
        except Exception as e:
            logger.exception(
                "SERVER get_diff_with: Error during workspace.diff() execution."
            )
            diff = f"# ERROR GENERATING DIFF: {e}"

        return diff


async def main(user_prompt="Minimal counter button application"):
    async with dagger.Connection(
        dagger.Config(log_output=open(os.devnull, "w"))
    ) as client:
        fsm_app: FSMApplication = await FSMApplication.start_fsm(client, user_prompt)

        while fsm_app.current_state not in (FSMState.COMPLETE, FSMState.FAILURE):
            await fsm_app.fsm.send(FSMEvent("CONFIRM"))

        context = fsm_app.fsm.context
        if fsm_app.maybe_error():
            logger.error(f"Application run failed: {context.error or 'Unknown error'}")
        else:
            logger.info("Application run completed successfully")
            logger.info(f"Generated {len(context.files)} files")
            diff = await fsm_app.get_diff_with({})
            logger.info("Diff:")
            logger.info(diff)
            snapshot = {k: v for k, v in fsm_app.fsm.context.files.items()}
            logger.info("Applying edit to application.")
            await fsm_app.apply_changes("Add header that says 'Hello World'")

            if fsm_app.maybe_error():
                logger.error(
                    f"Failed to apply edit: {context.error or 'Unknown error'}"
                )
            else:
                logger.info("Edit applied successfully")
                diff = await fsm_app.get_diff_with(snapshot)
                logger.info("Diff:")
                logger.info(diff)


if __name__ == "__main__":
    anyio.run(main)
