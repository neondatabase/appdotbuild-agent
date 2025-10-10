import os
import anyio
import logging
import enum
from typing import Dict, Self, Optional, Literal, Any
from dataclasses import dataclass
from core.statemachine import StateMachine, State, Context
from core.application import BaseApplicationContext
from core.dagger_utils import write_files_bulk
from llm.utils import get_vision_llm_client, get_best_coding_llm_client
from core.actors import BaseData
from core.base_node import Node
from core.statemachine import MachineCheckpoint
from core.workspace import Workspace
from axum_agent.actors import RustActor
import dagger

# Set up logging
logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)
for package in ["urllib3", "httpx", "google_genai.models"]:
    logging.getLogger(package).setLevel(logging.WARNING)


class FSMState(str, enum.Enum):
    DATA_MODEL_GENERATION = "data_model_generation"
    REVIEW_DATA_MODEL = "review_data_model"
    DATA_MODEL_APPLY_FEEDBACK = "data_model_apply_feedback"
    HANDLERS_GENERATION = "handlers_generation"
    REVIEW_HANDLERS = "review_handlers"
    HANDLERS_APPLY_FEEDBACK = "handlers_apply_feedback"
    UI_GENERATION = "ui_generation"
    REVIEW_UI = "review_ui"
    UI_APPLY_FEEDBACK = "ui_apply_feedback"
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
class ApplicationContext(BaseApplicationContext, Context):
    """Context for the Rust application state machine"""

    def dump(self) -> dict:
        """Dump context to a serializable dictionary"""
        # Use base dump method
        return self.dump_base()

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
    def base_execution_plan(cls, settings: dict[str, Any] | None = None) -> str:
        return "\n".join(
            [
                "1. Data model generation - Define Rust structs, database schema via Diesel migrations",
                "2. Handlers generation - Implement Axum route handlers and API logic",
                "3. UI generation - Create HTMX templates and frontend interactions",
                "",
                "The result application will be based on Rust, Axum, Diesel ORM and HTMX. Focus on type safety and simplicity.",
            ]
        )

    @classmethod
    def template_path(cls) -> str:
        return "./axum_agent/template"

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
            logger.exception("Setting error in context:", exc_info=error)
            ctx.error = str(error)
            ctx.error_type = error.__class__.__name__

        llm = get_best_coding_llm_client()
        vlm = get_vision_llm_client()

        workspace = await Workspace.create(
            client=client,
            base_image="rust:1.85-alpine",
            context=client.host().directory("./axum_agent/template"),
            setup_cmd=[
                ["apk", "add", "--no-cache", "musl-dev", "gcc", "pkgconfig", "build-base", "perl"],
                ["mkdir", "-p", "src"],
                ["sh", "-c", "echo 'fn main() {}' > src/main.rs"],
                ["cargo", "build", "--release", "--quiet"],
                ["rm", "-rf", "src", "target/release/deps/*main*", "target/release/*main*"],
            ],
        )

        event_callback = settings.get("event_callback") if settings else None

        # Create separate actor instances for data model, handlers, UI, and editing
        data_model_actor = RustActor(
            llm=llm,
            vlm=vlm,
            workspace=workspace.clone(),
            beam_width=settings.get("beam_width", 1) if settings else 1,
            max_depth=settings.get("max_depth", 50) if settings else 50,
            event_callback=event_callback,
            mode="data_model",
        )

        handlers_actor = RustActor(
            llm=llm,
            vlm=vlm,
            workspace=workspace.clone(),
            beam_width=settings.get("beam_width", 1) if settings else 1,
            max_depth=settings.get("max_depth", 50) if settings else 50,
            event_callback=event_callback,
            mode="handlers",
        )

        ui_actor = RustActor(
            llm=llm,
            vlm=vlm,
            workspace=workspace.clone(),
            beam_width=settings.get("beam_width", 1) if settings else 1,
            max_depth=settings.get("max_depth", 50) if settings else 50,
            event_callback=event_callback,
            mode="ui",
        )

        edit_actor = RustActor(
            llm=llm,
            vlm=vlm,
            workspace=workspace.clone(),
            beam_width=1,  # Use narrower beam for edits
            max_depth=50,  # Shorter depth for focused edits
            event_callback=event_callback,
            mode="auto",  # Edit mode uses auto-detection
        )

        # Define state machine states
        states = State[ApplicationContext, FSMEvent](
            on={
                FSMEvent("CONFIRM"): FSMState.DATA_MODEL_GENERATION,
                FSMEvent("FEEDBACK"): FSMState.APPLY_FEEDBACK,
            },
            states={
                FSMState.DATA_MODEL_GENERATION: State(
                    invoke={
                        "src": data_model_actor,
                        "input_fn": lambda ctx: (
                            {},  # files - empty for data model generation
                            ctx.feedback_data or ctx.user_prompt,
                        ),
                        "on_done": {
                            "target": FSMState.REVIEW_DATA_MODEL,
                            "actions": [update_node_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.REVIEW_DATA_MODEL: State(
                    on={
                        FSMEvent("CONFIRM"): FSMState.HANDLERS_GENERATION,
                        FSMEvent("FEEDBACK"): FSMState.DATA_MODEL_APPLY_FEEDBACK,
                    },
                ),
                FSMState.DATA_MODEL_APPLY_FEEDBACK: State(
                    invoke={
                        "src": data_model_actor,
                        "input_fn": lambda ctx: (
                            ctx.files,
                            ctx.feedback_data,
                        ),
                        "on_done": {
                            "target": FSMState.REVIEW_DATA_MODEL,
                            "actions": [update_node_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.HANDLERS_GENERATION: State(
                    invoke={
                        "src": handlers_actor,
                        "input_fn": lambda ctx: (
                            ctx.files,
                            ctx.feedback_data or ctx.user_prompt,
                        ),
                        "on_done": {
                            "target": FSMState.REVIEW_HANDLERS,
                            "actions": [update_node_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.REVIEW_HANDLERS: State(
                    on={
                        FSMEvent("CONFIRM"): FSMState.UI_GENERATION,
                        FSMEvent("FEEDBACK"): FSMState.HANDLERS_APPLY_FEEDBACK,
                    },
                ),
                FSMState.HANDLERS_APPLY_FEEDBACK: State(
                    invoke={
                        "src": handlers_actor,
                        "input_fn": lambda ctx: (
                            ctx.files,
                            ctx.feedback_data,
                        ),
                        "on_done": {
                            "target": FSMState.REVIEW_HANDLERS,
                            "actions": [update_node_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.UI_GENERATION: State(
                    invoke={
                        "src": ui_actor,
                        "input_fn": lambda ctx: (
                            ctx.files,
                            ctx.feedback_data or ctx.user_prompt,
                        ),
                        "on_done": {
                            "target": FSMState.REVIEW_UI,
                            "actions": [update_node_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.REVIEW_UI: State(
                    on={
                        FSMEvent("CONFIRM"): FSMState.COMPLETE,
                        FSMEvent("FEEDBACK"): FSMState.UI_APPLY_FEEDBACK,
                    },
                ),
                FSMState.UI_APPLY_FEEDBACK: State(
                    invoke={
                        "src": ui_actor,
                        "input_fn": lambda ctx: (
                            ctx.files,
                            ctx.feedback_data,
                        ),
                        "on_done": {
                            "target": FSMState.REVIEW_UI,
                            "actions": [update_node_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.APPLY_FEEDBACK: State(
                    invoke={
                        "src": edit_actor,
                        "input_fn": lambda ctx: (
                            ctx.files,
                            ctx.user_prompt,
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
                    }
                ),
                FSMState.COMPLETE: State(
                    on={
                        FSMEvent("FEEDBACK"): FSMState.APPLY_FEEDBACK,
                    }
                ),
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

    def is_agent_search_failed_error(self) -> bool:
        """Check if the error is an AgentSearchFailedException"""
        return self.fsm.context.error_type == "AgentSearchFailedException"

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
            case FSMState.REVIEW_DATA_MODEL:
                return {"data_models": self.truncated_files}
            case FSMState.REVIEW_HANDLERS:
                return {"handlers": self.truncated_files}
            case FSMState.REVIEW_UI:
                return {"ui": self.truncated_files}
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
            case FSMState.REVIEW_DATA_MODEL | FSMState.REVIEW_HANDLERS | FSMState.REVIEW_UI:
                actions = {"confirm": "Accept current output and continue"}
                logger.debug(
                    f"Review state detected: {self.current_state}, offering confirm action"
                )
            case FSMState.COMPLETE:
                actions = {
                    "complete": "Finalize and get all artifacts",
                    "change": "Submit feedback for the current FSM state and trigger revision",
                }
                logger.debug(
                    "FSM is in COMPLETE state, offering complete and change actions"
                )
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
            start = await write_files_bulk(start, snapshot, self.client)
            start = start.with_exec(["git", "add", "."]).with_exec(
                ["git", "commit", "-m", "'snapshot'"]
            )
        else:
            logger.info(
                "SERVER get_diff_with: Snapshot is empty. Diff will be against template + FSM context files."
            )
            # If no snapshot, create an empty initial commit
            start = start.with_exec(["git", "add", "."]).with_exec(
                ["git", "commit", "-m", "'initial'", "--allow-empty"]
            )

        # Add template files (they will appear in diff if not in snapshot)
        template_dir = self.client.host().directory("./axum_agent/template")
        start = start.with_directory(".", template_dir)

        # Add FSM context files on top
        start = await write_files_bulk(start, self.fsm.context.files, self.client)

        logger.info(
            "SERVER get_diff_with: Calling workspace.diff() to generate final diff."
        )
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

        return diff


async def main(user_prompt="Minimal persistent counter application"):
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
            logger.info("Applying edit to application.")
            await fsm_app.apply_changes("Add a button that says 'Hello Rust'")

            if fsm_app.maybe_error():
                logger.error(
                    f"Failed to apply edit: {context.error or 'Unknown error'}"
                )
            else:
                logger.info("Edit applied successfully")


if __name__ == "__main__":
    anyio.run(main)
