"""Dagger-based app generation pipeline with caching and parallelism."""

import asyncio
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import dagger

from cli.generation.codegen import GenerationMetrics

logger = logging.getLogger(__name__)


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


def _check_binary_format(binary_path: Path) -> None:
    """Check if binary is Linux-compatible for container execution.

    Raises:
        RuntimeError: If binary is not Linux ELF format
    """
    try:
        result = subprocess.run(
            ["file", str(binary_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        output = result.stdout.lower()

        if "mach-o" in output or "darwin" in output:
            raise RuntimeError(
                f"Binary {binary_path} is macOS format (Mach-O), but Dagger runs Linux containers.\n"
                f"Please provide a Linux build. For Go: GOOS=linux GOARCH=arm64 go build ...\n"
                f"Output from 'file': {result.stdout.strip()}"
            )

        if "elf" not in output:
            logger.warning(
                f"Binary {binary_path} may not be Linux-compatible: {result.stdout.strip()}"
            )
    except FileNotFoundError:
        # 'file' command not available, skip check
        pass


class DaggerAppGenerator:
    """Runs app generation in Dagger container with caching."""

    def __init__(
        self,
        output_dir: Path,
        mcp_binary: Path | None = None,
        stream_logs: bool = True,
    ):
        """Initialize Dagger app generator.

        Args:
            output_dir: Directory to export generated apps to
            mcp_binary: Path to MCP binary (only needed for litellm backend)
            stream_logs: Whether to stream Dagger logs to stderr
        """
        if mcp_binary is not None:
            _check_binary_format(mcp_binary)
        self.mcp_binary = mcp_binary
        self.output_dir = output_dir
        self.stream_logs = stream_logs

    async def generate_single(
        self,
        prompt: str,
        app_name: str,
        backend: str = "claude",
        model: str | None = None,
        mcp_args: list[str] | None = None,
    ) -> tuple[Path | None, Path, GenerationMetrics | None]:
        """Generate single app, export app dir + logs.

        Returns:
            tuple of (app_dir or None, log_file, metrics or None) paths on host.
            app_dir is None if agent didn't create an app.
        """
        if backend == "litellm" and self.mcp_binary is None:
            raise ValueError("mcp_binary is required for litellm backend")

        if self.stream_logs:
            cfg = dagger.Config(log_output=sys.stderr)
        else:
            cfg = dagger.Config(log_output=open(os.devnull, "w"))
        async with dagger.Connection(cfg) as client:
            container = await self._build_container(client, backend)
            return await self._run_generation(
                client, container, prompt, app_name, backend, model, mcp_args
            )

    async def _run_generation(
        self,
        client: dagger.Client,
        base_container: dagger.Container,
        prompt: str,
        app_name: str,
        backend: str,
        model: str | None,
        mcp_args: list[str] | None,
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
        if mcp_args:
            cmd.append(f"--mcp_args={json.dumps(mcp_args)}")

        # mount cache volume for python deps (safe for concurrent access)
        # note: npm cache is NOT cached to avoid corruption under parallel execution
        # npm packages are already optimized via BuildKit cache mounts in Dockerfile
        python_cache = client.cache_volume("klaudbiusz-python-cache")
        container = base_container.with_mounted_cache(
            "/home/klaudbiusz/.cache", python_cache, owner="klaudbiusz:klaudbiusz"
        )

        # run generation and sync to force evaluation
        result = await container.with_exec(cmd).sync()

        # prepare log file path
        log_file_local = self.output_dir / "logs" / f"{app_name}.log"
        log_file_local.parent.mkdir(parents=True, exist_ok=True)

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
            await result.directory(app_output).export(str(app_dir_local))
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
        mcp_args: list[str] | None = None,
        max_concurrency: int = 4,
        on_complete: Callable[[str, bool], None] | None = None,
    ) -> list[tuple[str, Path | None, Path | None, GenerationMetrics | None, str | None]]:
        """Generate multiple apps with Dagger parallelism.

        Uses a single Dagger connection for all generations, allowing Dagger
        to optimize container reuse and parallel execution.

        Args:
            prompts: dict mapping app_name to prompt
            backend: "claude" or "litellm"
            model: model name (required for litellm)
            mcp_args: optional MCP server args (litellm only)
            max_concurrency: max parallel generations
            on_complete: callback(app_name, success) called when each app finishes

        Returns:
            list of (app_name, app_dir, log_file, metrics, error) tuples
        """
        if backend == "litellm" and self.mcp_binary is None:
            raise ValueError("mcp_binary is required for litellm backend")

        # suppress dagger output for bulk runs
        cfg = dagger.Config(log_output=open(os.devnull, "w"))

        async with dagger.Connection(cfg) as client:
            # build container once, reuse for all generations
            base_container = await self._build_container(client, backend)
            sem = asyncio.Semaphore(max_concurrency)

            async def run_with_sem(
                app_name: str, prompt: str
            ) -> tuple[str, Path | None, Path | None, GenerationMetrics | None, str | None]:
                async with sem:
                    try:
                        app_dir, log_file, metrics = await self._run_generation(
                            client, base_container, prompt, app_name, backend, model, mcp_args
                        )
                        if on_complete:
                            on_complete(app_name, True)
                        return (app_name, app_dir, log_file, metrics, None)
                    except Exception as e:
                        if on_complete:
                            on_complete(app_name, False)
                        log_path = self.output_dir / "logs" / f"{app_name}.log"
                        return (app_name, None, log_path if log_path.exists() else None, None, str(e))

            tasks = [run_with_sem(name, prompt) for name, prompt in prompts.items()]
            return await asyncio.gather(*tasks)

    async def _build_container(self, client: dagger.Client, backend: str = "claude") -> dagger.Container:
        """Build container from Dockerfile with layer caching."""
        # build context excluding generated files
        context = client.host().directory(
            ".",
            exclude=[
                "app/",
                "app-eval/",
                "results/",
                ".venv/",
                "__pycache__/",
                ".git/",
            ],
        )

        # build from Dockerfile (leverages BuildKit cache)
        container = context.docker_build()

        # pass through env vars from host
        env_vars = [
            "ANTHROPIC_API_KEY",
            "NEON_DATABASE_URL",
        ]
        for var in env_vars:
            if val := os.environ.get(var):
                container = container.with_env_variable(var, val)

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

        # litellm backend still needs MCP binary
        if backend == "litellm" and self.mcp_binary is not None:
            container = container.with_file(
                "/usr/local/bin/edda_mcp",
                client.host().file(str(self.mcp_binary)),
                permissions=0o755,
            )

            # mount appkit template if available locally (for testing local template changes)
            mcp_binary_dir = self.mcp_binary.parent
            appkit_template = mcp_binary_dir / "experimental" / "aitools" / "templates" / "appkit"
            if appkit_template.exists():
                container = container.with_directory(
                    "/opt/appkit-template",
                    client.host().directory(str(appkit_template)),
                )
                container = container.with_env_variable(
                    "DATABRICKS_APPKIT_TEMPLATE_PATH", "/opt/appkit-template"
                )

        return container
