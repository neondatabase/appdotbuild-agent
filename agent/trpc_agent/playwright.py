import re
import os
import logging
import contextlib
from collections import defaultdict
from typing import Literal
from tempfile import TemporaryDirectory
import jinja2
from trpc_agent import playbooks
from core.base_node import Node
from core.workspace import ExecResult
from core.actors import BaseData
from core.postgres_utils import create_postgres_service, pg_health_check_cmd
from llm.common import AsyncLLM, Message, TextRaw, AttachedFiles
from llm.utils import merge_text, extract_tag

import dagger

logger = logging.getLogger(__name__)


async def drizzle_push(
    client: dagger.Client, ctr: dagger.Container, postgresdb: dagger.Service | None
) -> ExecResult:
    """Run drizzle-kit push with postgres service."""

    if postgresdb is None:
        postgresdb = create_postgres_service(client)

    push_ctr = (
        ctr.with_exec(["apk", "--update", "add", "postgresql-client"])
        .with_service_binding("postgres", postgresdb)
        .with_env_variable(
            "APP_DATABASE_URL", "postgres://postgres:postgres@postgres:5432/postgres"
        )
        .with_exec(pg_health_check_cmd())
        .with_workdir("server")
        .with_exec(["bun", "run", "drizzle-kit", "push", "--force"])
    )
    result = await ExecResult.from_ctr(push_ctr)
    return result


@contextlib.contextmanager
def ensure_dir(dir_path: str | None):
    if dir_path is not None:
        yield dir_path
    else:
        with TemporaryDirectory() as temp_dir:
            yield temp_dir


class PlaywrightRunner:
    def __init__(self, vlm: AsyncLLM):
        self._ts_cleanup_pattern = re.compile(r"(\?v=)[a-f0-9]+(:[0-9]+:[0-9]+)?")
        self.vlm = vlm
        self.counter = defaultdict(int)

    @staticmethod
    async def run(
        node: Node[BaseData],
        mode: Literal["client", "full"] = "client",
        log_dir: str | None = None,
    ) -> tuple[ExecResult, str | None]:
        logger.info("Running Playwright tests")

        workspace = node.data.workspace
        ctr = workspace.ctr.with_exec(["bun", "install", "."])

        match mode:
            case "client":
                entrypoint = "dev:client"
                postgresdb = None
            case "full":
                postgresdb = create_postgres_service(workspace.client)
                push_result = await drizzle_push(workspace.client, ctr, postgresdb)
                if push_result.exit_code != 0:
                    return push_result, f"Drizzle push failed: {push_result.stderr}"
                logger.info("Drizzle push succeeded")
                entrypoint = "dev:all"

        app_ctr = await ctr.with_entrypoint(
            ["bun", "run", entrypoint]
        ).with_exposed_port(5173)

        if postgresdb:
            app_ctr = (
                app_ctr.with_service_binding("postgres", postgresdb)
                .with_exposed_port(2022)
                .with_exposed_port(5173)
                .with_env_variable(
                    "APP_DATABASE_URL",
                    "postgres://postgres:postgres@postgres:5432/postgres",
                )
            )

        # start the app as a service
        app_service = app_ctr.as_service()

        # implement health check for backend
        if mode == "full":
            logger.info("Waiting for backend service to start...")
            backend_check = (
                workspace.client.container()
                .from_("alpine:latest")
                .with_exec(["apk", "add", "--no-cache", "curl"])
                .with_service_binding("app", app_service)
                .with_exec(
                    [
                        "sh",
                        "-c",
                        "for i in $(seq 1 30); do "
                        "curl -f http://app:2022/healthcheck 2>/dev/null && exit 0; "
                        "echo 'Waiting for backend...' && sleep 1; "
                        "done; exit 1",
                    ]
                )
            )
            backend_result = await ExecResult.from_ctr(backend_check)
            if backend_result.exit_code != 0:
                return (
                    backend_result,
                    f"Backend service failed to start: {backend_result.stderr}",
                )

            logger.info("Backend is ready")

        logger.info("App service is ready")

        with ensure_dir(log_dir) as temp_dir:
            result = await node.data.workspace.run_playwright(
                app_service,
                temp_dir,
            )
            if result.exit_code == 0:
                logger.debug("Playwright tests succeeded")
                return result, None

            logger.warning(f"Playwright tests failed with exit code {result.exit_code}")
            return result, f"Error running Playwright tests: {result.stderr}"

    async def evaluate(
        self,
        node: Node[BaseData],
        user_prompt: str,
        mode: Literal["client", "full"] = "client",
    ) -> list[str]:
        errors = []
        with TemporaryDirectory() as temp_dir:
            match mode:
                case "client":
                    prompt_template = playbooks.FRONTEND_VALIDATION_PROMPT
                case "full":
                    prompt_template = playbooks.FULL_UI_VALIDATION_PROMPT
                case _:
                    raise ValueError(f"Unknown mode: {mode}")

            _, err = await self.run(node, log_dir=temp_dir, mode=mode)
            if err:
                errors.append(err)
            else:
                browsers = (
                    "chromium",
                    "webkit",
                )  # firefox is flaky, let's skip it for now?
                expected_files = [f"{browser}-screenshot.png" for browser in browsers]
                console_logs = ""
                for browser in browsers:
                    console_log_file = os.path.join(temp_dir, f"{browser}-console.log")
                    screenshot_file = os.path.join(
                        temp_dir, f"{browser}-screenshot.png"
                    )
                    if not os.path.exists(os.path.join(temp_dir, screenshot_file)):
                        errors.append(f"Could not make screenshot: {screenshot_file}")

                    if os.path.exists(os.path.join(temp_dir, console_log_file)):
                        with open(console_log_file, "r") as f:
                            console_logs += f"\n{browser}:\n"
                            logs = f.read()
                            # remove stochastic parts of the logs for caching
                            console_logs += self._ts_cleanup_pattern.sub(r"\1", logs)

                prompt = jinja2.Environment().from_string(prompt_template)
                prompt_rendered = prompt.render(
                    console_logs=console_logs, user_prompt=user_prompt
                )
                message = Message(role="user", content=[TextRaw(prompt_rendered)])
                self.counter[user_prompt] += 1  # for cache invalidation between runs
                attach_files = AttachedFiles(
                    files=[os.path.join(temp_dir, file) for file in expected_files],
                    _cache_key=node.data.file_cache_key
                    + str(self.counter[user_prompt]),
                )
                vlm_feedback = await self.vlm.completion(
                    messages=[message],
                    max_tokens=1024,
                    attach_files=attach_files,
                )
                (vlm_feedback,) = merge_text(list(vlm_feedback.content))
                vlm_text = vlm_feedback.text  # pyright: ignore

                answer = extract_tag(vlm_text, "answer") or ""
                reason = extract_tag(vlm_text, "reason") or ""
                if "no" in answer.lower():
                    logger.info(
                        f"Playwright validation failed. Answer: {answer}, reason: {reason}"
                    )
                    errors.append(
                        f"Playwright validation failed with the reason: {reason}, console_logs: {console_logs}"
                    )
                else:
                    logger.info(
                        f"Playwright validation succeeded. Answer: {answer}, reason: {reason}"
                    )
        return errors
