"""Dagger-based app generation pipeline with caching and parallelism."""

import asyncio
import json
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path

import dagger

from cli.generation.codegen import GenerationMetrics

logger = logging.getLogger(__name__)

BUILD_CONTEXT_EXCLUDES = [
    "app/",
    "app-*/",
    "app-eval/",
    "archive/",
    "results/",
    ".venv/",
    "__pycache__/",
    ".git/",
]

# Keep generated source, logs, and metrics, but skip dependency trees.
EXPORT_EXCLUDE_PATHS = [
    "**/node_modules/**",
]

# Hard caps for a single app execution.
APP_EXEC_TIMEOUT_SEC = 35 * 60
# Retry once when the failure is timeout-shaped.
BULK_TIMEOUT_RETRIES = 1


def _read_metrics_from_app(app_dir: Path) -> GenerationMetrics | None:
    """Read metrics from generation_metrics.json in app directory."""
    metrics_file = app_dir / "generation_metrics.json"
    if not metrics_file.exists():
        return None

    try:
        data = json.loads(metrics_file.read_text())
        return GenerationMetrics(
            cost_usd=data.get("cost_usd", 0.0),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            turns=data.get("turns", 0),
        )
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to parse generation metrics: {e}")
        return None


class DaggerAppGenerator:
    """Runs app generation in Dagger container with caching."""

    def __init__(
        self,
        output_dir: Path,
        stream_logs: bool = True,
        databricks_cli_path: Path | None = None,
    ):
        """Initialize Dagger app generator.

        Args:
            output_dir: Directory to export generated apps to
            stream_logs: Whether to stream Dagger logs to stderr
            databricks_cli_path: Optional host path to custom databricks CLI binary
        """
        self.output_dir = output_dir
        self.stream_logs = stream_logs
        self.databricks_cli_path = databricks_cli_path

    async def generate_single(
        self,
        prompt: str,
        app_name: str,
        backend: str = "claude",
        model: str | None = None,
    ) -> tuple[Path | None, Path, GenerationMetrics | None]:
        """Generate single app, export app dir + logs.

        Returns:
            tuple of (app_dir or None, log_file, metrics or None) paths on host.
            app_dir is None if agent didn't create an app.
        """
        if self.stream_logs:
            cfg = dagger.Config(log_output=sys.stderr)
        else:
            cfg = dagger.Config(log_output=open(os.devnull, "w"))
        async with dagger.Connection(cfg) as client:
            container = await self._build_container(client)
            return await self._run_generation(
                container, prompt, app_name, backend, model
            )

    async def _run_generation(
        self,
        base_container: dagger.Container,
        prompt: str,
        app_name: str,
        backend: str,
        model: str | None,
    ) -> tuple[Path | None, Path, GenerationMetrics | None]:
        """Run generation in container and export results."""
        # path inside container for generated app
        app_output = f"/workspace/{app_name}"

        # build command using container_runner.py (already in image via Dockerfile COPY)
        cmd = [
            "python",
            "cli/generation/container_runner.py",
            prompt,
            f"--app_name={app_name}",
            f"--backend={backend}",
        ]
        if model:
            cmd.append(f"--model={model}")

        container = base_container

        # prepare log file path
        log_file_local = self.output_dir / "logs" / f"{app_name}.log"
        log_file_local.parent.mkdir(parents=True, exist_ok=True)
        log_file_local.write_text("")

        # run generation and sync to force evaluation
        try:
            result = await asyncio.wait_for(
                container.with_exec(cmd).sync(),
                timeout=APP_EXEC_TIMEOUT_SEC if APP_EXEC_TIMEOUT_SEC > 0 else None,
            )
        except TimeoutError as e:
            timeout_msg = (
                f"Generation timed out after {APP_EXEC_TIMEOUT_SEC}s for app '{app_name}'. "
                "Marking as failed and releasing bulk slot."
            )
            log_file_local.write_text(f"=== TIMEOUT ===\n{timeout_msg}\n")
            raise TimeoutError(timeout_msg) from e

        # capture stdout/stderr - even on failure we want to save what we can
        exec_error: dagger.ExecError | None = None
        try:
            log_content = await result.stdout()
            stderr_content = await result.stderr()
            full_log = f"{log_content}\n\n=== STDERR ===\n{stderr_content}" if stderr_content else log_content
            log_file_local.write_text(full_log)
        except dagger.ExecError as e:
            # container command failed - save error output as log
            full_log = f"=== EXEC ERROR ===\n{e}\n\n=== STDOUT ===\n{e.stdout}\n\n=== STDERR ===\n{e.stderr}"
            log_file_local.write_text(full_log)
            exec_error = e  # save error but still try to export app

        # export app directory (if it exists) - try even after ExecError
        # because the app may have been built successfully before SDK shutdown error
        app_dir_local = self.output_dir / app_name
        try:
            app_dir_filtered = result.directory(app_output).without_files(EXPORT_EXCLUDE_PATHS)
            await app_dir_filtered.export(str(app_dir_local))
            # app was exported successfully - if we had an ExecError, log it but don't fail
            if exec_error:
                logger.warning(f"Container exited with error but app was exported: {exec_error}")
        except dagger.QueryError as e:
            if "no such file or directory" in str(e):
                # agent didn't create an app directory
                if exec_error:
                    # no app AND exec error - this is a real failure
                    raise exec_error
                return None, log_file_local, None
            raise

        # read metrics from generation_metrics.json
        metrics = _read_metrics_from_app(app_dir_local)
        return app_dir_local, log_file_local, metrics

    async def generate_bulk(
        self,
        prompts: dict[str, str],
        backend: str = "claude",
        model: str | None = None,
        max_concurrency: int = 4,
        on_complete: Callable[[str, bool], None] | None = None,
    ) -> list[tuple[str, Path | None, Path | None, GenerationMetrics | None, str | None]]:
        """Generate multiple apps with Dagger parallelism.

        Uses a single Dagger connection for all generations, allowing Dagger
        to optimize container reuse and parallel execution.

        Args:
            prompts: dict mapping app_name to prompt
            backend: "claude" or "opencode"
            model: model name (optional, for opencode non-default model)
            max_concurrency: max parallel generations
            on_complete: callback(app_name, success) called when each app finishes

        Returns:
            list of (app_name, app_dir, log_file, metrics, error) tuples
        """
        # suppress dagger output for bulk runs
        cfg = dagger.Config(log_output=open(os.devnull, "w"))

        async with dagger.Connection(cfg) as client:
            # build container once, reuse for all generations
            base_container = await self._build_container(client)
            sem = asyncio.Semaphore(max_concurrency)

            def is_timeout_failure(error: Exception, log_path: Path) -> bool:
                message = str(error).lower()
                if isinstance(error, TimeoutError):
                    return True
                if "timeout" in message or "timed out" in message or "code 124" in message:
                    return True
                if log_path.exists():
                    try:
                        content = log_path.read_text().lower()
                    except OSError:
                        return False
                    return "=== timeout ===" in content or "timed out" in content
                return False

            async def run_with_sem(
                app_name: str, prompt: str
            ) -> tuple[str, Path | None, Path | None, GenerationMetrics | None, str | None]:
                async with sem:
                    log_path = self.output_dir / "logs" / f"{app_name}.log"
                    max_attempts = BULK_TIMEOUT_RETRIES + 1

                    for attempt in range(max_attempts):
                        try:
                            app_dir, log_file, metrics = await self._run_generation(
                                base_container, prompt, app_name, backend, model
                            )
                            if on_complete:
                                on_complete(app_name, True)
                            return (app_name, app_dir, log_file, metrics, None)
                        except Exception as e:
                            if attempt < BULK_TIMEOUT_RETRIES and is_timeout_failure(e, log_path):
                                logger.warning(
                                    f"Timeout while generating '{app_name}', retrying "
                                    f"({attempt + 1}/{BULK_TIMEOUT_RETRIES})"
                                )
                                continue
                            if on_complete:
                                on_complete(app_name, False)
                            return (app_name, None, log_path if log_path.exists() else None, None, str(e))

            tasks = [run_with_sem(name, prompt) for name, prompt in prompts.items()]
            return await asyncio.gather(*tasks)

    async def _build_container(self, client: dagger.Client) -> dagger.Container:
        """Build container from Dockerfile with layer caching."""
        # build context excluding generated files
        context = client.host().directory(
            ".",
            exclude=BUILD_CONTEXT_EXCLUDES,
        )

        if self.databricks_cli_path is not None:
            resolved_cli_path = self.databricks_cli_path.resolve()
            if not resolved_cli_path.is_file():
                raise ValueError(
                    f"--databricks_cli_path must point to a file, got: {resolved_cli_path}"
                )
            # Explicit branch: do not install default CLI, copy custom binary instead.
            container = context.docker_build(
                build_args=[dagger.BuildArg(name="INSTALL_DATABRICKS_CLI", value="0")]
            )
            container = container.with_file(
                "/usr/local/bin/databricks",
                client.host().file(str(resolved_cli_path)),
                permissions=0o755,
            )
        else:
            # Explicit branch: install default CLI from Dockerfile.
            container = context.docker_build()

        # pass through env vars from host (LLM providers + internal)
        env_vars = [
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "NEON_DATABASE_URL",
        ]
        for var in env_vars:
            if val := os.environ.get(var):
                container = container.with_env_variable(var, val)

        # map GEMINI_API_KEY to GOOGLE_GENERATIVE_AI_API_KEY (AI SDK uses this name)
        if gemini_key := os.environ.get("GEMINI_API_KEY"):
            container = container.with_env_variable("GOOGLE_GENERATIVE_AI_API_KEY", gemini_key)

        # create opencode auth.json from env var for OpenRouter
        # directories pre-created in Dockerfile
        if openrouter_key := os.environ.get("OPENROUTER_API_KEY"):
            auth_json = f'{{"openrouter": {{"type": "api", "key": "{openrouter_key}"}}}}'
            container = container.with_new_file(
                "/home/klaudbiusz/.local/share/opencode/auth.json",
                auth_json,
                owner="klaudbiusz:klaudbiusz",
            )

        # mount databricks config for CLI authentication (OAuth profile)
        # container runs as 'klaudbiusz' user (see Dockerfile)
        databrickscfg = Path.home() / ".databrickscfg"
        if databrickscfg.exists():
            container = container.with_file(
                "/home/klaudbiusz/.databrickscfg",
                client.host().file(str(databrickscfg)),
                owner="klaudbiusz:klaudbiusz",
            )

        # mount databricks directory for OAuth token cache, CLI state, and skills
        # required when using auth_type = databricks-cli
        # skills are symlinked from ~/.databricks/agent-skills/ to ~/.claude/skills/
        databricks_dir = Path.home() / ".databricks"
        if databricks_dir.exists():
            container = container.with_directory(
                "/home/klaudbiusz/.databricks",
                client.host().directory(str(databricks_dir)),
                owner="klaudbiusz:klaudbiusz",
            )

        # mount claude skills directory for SDK skill support (claude and opencode backends)
        # resolve symlinks since dagger doesn't follow them across mount boundaries
        claude_skills_dir = Path.home() / ".claude" / "skills"
        if claude_skills_dir.exists():
            for skill_path in claude_skills_dir.iterdir():
                # resolve symlinks to get actual directory
                resolved_path = skill_path.resolve()
                if resolved_path.is_dir():
                    container_path = f"/home/klaudbiusz/.claude/skills/{skill_path.name}"
                    container = container.with_directory(
                        container_path,
                        client.host().directory(str(resolved_path)),
                        owner="klaudbiusz:klaudbiusz",
                    )

        # mount opencode skills directory for opencode backend
        # opencode discovers skills from ~/.config/opencode/skills/
        opencode_skills_dir = Path.home() / ".config" / "opencode" / "skills"
        if opencode_skills_dir.exists():
            for skill_path in opencode_skills_dir.iterdir():
                resolved_path = skill_path.resolve()
                if resolved_path.is_dir():
                    container_path = f"/home/klaudbiusz/.config/opencode/skills/{skill_path.name}"
                    container = container.with_directory(
                        container_path,
                        client.host().directory(str(resolved_path)),
                        owner="klaudbiusz:klaudbiusz",
                    )

        return container
