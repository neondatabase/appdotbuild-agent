import os
import anyio
import logging
import enum
from typing import Dict, Self, Optional, Literal, Any
from dataclasses import dataclass
from core.statemachine import StateMachine, State, Context
from core.application import BaseApplicationContext
from core.dagger_utils import write_files_bulk
from llm.utils import get_best_coding_llm_client, get_universal_llm_client
from llm.alloy import AlloyLLM
from core.actors import BaseData
from core.base_node import Node
from core.statemachine import MachineCheckpoint
from core.workspace import Workspace
from nicegui_agent.actors import NiceguiActor
from nicegui_agent import playbooks
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
    APPLICATION_GENERATION = "application_generation"
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
class ApplicationContext(BaseApplicationContext, Context):
    """Context for the fullstack application state machine"""

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
    def is_databricks_available(cls, settings: Dict[str, Any]) -> bool:
        settings = settings or {}
        databricks_host = settings.get("databricks_host")
        databricks_token = settings.get("databricks_token")
        return bool(databricks_host and databricks_token)

    @classmethod
    def base_execution_plan(cls, settings: Dict[str, Any] | None = None) -> str:
        settings = settings or {}

        databricks_part = (
            "This application can have access to Databricks Unity Catalog for data access"
            if cls.is_databricks_available(settings)
            else ""
        )

        return "\n".join(
            [
                "1. Data model generation - Define data structures, schemas, and models. ",
                "2. Application generation - Implement UI components and application logic. ",
                "",
                "The result application will be based on Python and NiceGUI framework. Persistent data will be stored in Postgres with SQLModel ORM. "
                "The application can include various UI components, event handling, and state management. ",
                "This application can use install new libraries if needed. ",
                databricks_part,
            ]
        )

    @classmethod
    def template_path(cls) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "./template")

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
        settings = settings or {}

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
            ctx.error_type = error.__class__.__name__

        async def run_final_steps(
            ctx: ApplicationContext, result: Node[BaseData]
        ) -> None:
            logger.info("Running final steps after application generation")
            await result.data.workspace.exec_mut(
                [
                    "uv",
                    "export",
                    "--no-hashes",
                    "--format",
                    "requirements-txt",
                    "--output-file",
                    "requirements.txt",
                    "--no-dev",
                ]
            )
            reqs = await result.data.workspace.read_file("requirements.txt")
            if reqs:
                ctx.files["requirements.txt"] = reqs

            # apply ruff lint fixes
            await result.data.workspace.exec_mut(
                [
                    "uv",
                    "run",
                    "ruff",
                    "check",
                    ".",
                    "--fix",
                ]
            )

            # apply ruff formatting
            await result.data.workspace.exec_mut(
                [
                    "uv",
                    "run",
                    "ruff",
                    "format",
                    ".",
                ]
            )

            # read all files again after modifications and update context
            for file in ctx.files.keys():
                if file.endswith(".py"):
                    content = await result.data.workspace.read_file(file)
                    if content is not None:
                        ctx.files[file] = content

        if os.getenv("USE_ALLOY_LLM"):
            llm = AlloyLLM.from_models(
                [get_best_coding_llm_client(), get_universal_llm_client()]
            )
        else:
            llm = get_best_coding_llm_client()

        workspace = await Workspace.create(
            client=client,
            base_image="alpine:3.21.3",
            context=client.host().directory("./nicegui_agent/template"),
            setup_cmd=[
                [
                    "apk",
                    "add",
                    "--update",
                    "--no-cache",
                    "curl",
                    "python3",
                    "nodejs",
                    "gcc",
                    "musl-dev",
                    "linux-headers",
                ],  # node for pyright, gcc/musl-dev for building ast-grep-cli
                [
                    "sh",
                    "-c",
                    "curl -LsSf https://astral.sh/uv/install.sh | XDG_BIN_HOME=/usr/local/bin sh",
                ],
                ["uv", "sync"],
            ],
        )

        # Extract event_callback from settings if provided
        event_callback = settings.pop("event_callback", None)

        use_databricks = cls.is_databricks_available(settings)
        databricks_host = settings.get("databricks_host", "")
        databricks_token = settings.get("databricks_token", "")

        if use_databricks:
            workspace = workspace.add_env_variable(
                "DATABRICKS_HOST", databricks_host
            ).add_env_variable("DATABRICKS_TOKEN", databricks_token)

        data_actor = NiceguiActor(
            llm=llm,
            workspace=workspace.clone(),
            beam_width=3,
            max_depth=50,
            system_prompt=playbooks.get_data_model_system_prompt(
                use_databricks=use_databricks
            ),
            files_allowed=["app/models.py"],
            event_callback=event_callback,
            databricks_host=databricks_host,
            databricks_token=databricks_token,
        )
        # ToDo: propagate crucial template files to DATA_MODEL_SYSTEM_PROMPT so they're cached
        app_actor = NiceguiActor(
            llm=llm,
            workspace=workspace.clone(),
            beam_width=3,
            max_depth=100,  # can be larger given every file change is a separate tool call,
            system_prompt=playbooks.get_application_system_prompt(),
            event_callback=event_callback,
            databricks_host=databricks_host,
            databricks_token=databricks_token,
        )
        # FixMe: second stage actor in general should not alter models.py, but on the edit stage it should

        # Define state machine states
        states = State[ApplicationContext, FSMEvent](
            on={
                FSMEvent("CONFIRM"): FSMState.DATA_MODEL_GENERATION,
                FSMEvent("FEEDBACK"): FSMState.APPLY_FEEDBACK,
            },
            states={
                FSMState.DATA_MODEL_GENERATION: State(
                    invoke={
                        "src": data_actor,
                        "input_fn": lambda ctx: (
                            {
                                k: v
                                for k, v in ctx.files.items()
                                if k != "requirements.txt"
                            },
                            ctx.feedback_data or ctx.user_prompt,
                        ),
                        "on_done": {
                            "target": FSMState.REVIEW_DATA_MODEL,
                            "actions": [update_node_files, run_final_steps],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.REVIEW_DATA_MODEL: State(
                    on={
                        FSMEvent("CONFIRM"): FSMState.APPLICATION_GENERATION,
                        FSMEvent("FEEDBACK"): FSMState.DATA_MODEL_APPLY_FEEDBACK,
                    },
                ),
                FSMState.DATA_MODEL_APPLY_FEEDBACK: State(
                    invoke={
                        "src": data_actor,
                        "input_fn": lambda ctx: (
                            {
                                k: v
                                for k, v in ctx.files.items()
                                if k != "requirements.txt"
                            },
                            ctx.feedback_data,
                        ),
                        "on_done": {
                            "target": FSMState.REVIEW_DATA_MODEL,
                            "actions": [update_node_files, run_final_steps],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.APPLICATION_GENERATION: State(
                    invoke={
                        "src": app_actor,
                        "input_fn": lambda ctx: (
                            {
                                k: v
                                for k, v in ctx.files.items()
                                if k != "requirements.txt"
                            },
                            ctx.feedback_data or ctx.user_prompt,
                        ),
                        "on_done": {
                            "target": FSMState.REVIEW_APPLICATION,
                            "actions": [update_node_files, run_final_steps],
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
                        "src": app_actor,
                        "input_fn": lambda ctx: (
                            {
                                k: v
                                for k, v in ctx.files.items()
                                if k != "requirements.txt"
                            },
                            ctx.feedback_data,
                        ),
                        "on_done": {
                            "target": FSMState.COMPLETE,
                            "actions": [update_node_files, run_final_steps],
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
            case FSMState.REVIEW_DATA_MODEL | FSMState.REVIEW_APPLICATION:
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

        tree_snapshot = await start.with_exec(["tree"]).stdout()
        logger.error(f"[ctr tree] [snapshot]\n{tree_snapshot}")

        # Add template files (they will appear in diff if not in snapshot)
        template_dir = self.client.host().directory("./nicegui_agent/template")
        start = start.with_directory(".", template_dir)
        logger.info("SERVER get_diff_with: Added template directory to workspace")

        tree_snapshot = await start.with_exec(["tree"]).stdout()
        logger.error(f"[ctr tree] [template]\n{tree_snapshot}")

        # Add FSM context files on top
        start = await write_files_bulk(start, self.fsm.context.files, self.client)

        tree_snapshot = await start.with_exec(["tree"]).stdout()
        logger.error(f"[ctr tree] [fsm_context]\n{tree_snapshot}")
        fsm_file_keys = list(self.fsm.context.files.keys())
        logger.error(f"[fsm context] [files] {fsm_file_keys}")

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
        diff_names_only = (
            await start.with_exec(["git", "add", "."])
            .with_exec(["git", "diff", "HEAD", "--name-only"])
            .stdout()
        )
        logger.error(f"[diff] [names] {diff_names_only}")

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
