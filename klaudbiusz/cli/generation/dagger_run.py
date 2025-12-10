"""Dagger-based app generation pipeline with caching and parallelism."""

import asyncio
import json
import logging
import os
import shutil
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
        stream_logs: bool = True,
        skill_path: Path | None = None,
        databricks_binary: Path | None = None,
    ):
        self.output_dir = output_dir
        self.stream_logs = stream_logs
        self.skill_path = skill_path or Path.home() / "dev/cli/experimental/apps-mcp/lib/skill/databricks-apps"
        self.databricks_binary = databricks_binary or Path.home() / "dev/cli/cli_linux"
        _check_binary_format(self.databricks_binary)

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
                client, container, prompt, app_name, backend, model
            )

    async def _run_generation(
        self,
        client: dagger.Client,
        base_container: dagger.Container,
        prompt: str,
        app_name: str,
        backend: str,
        model: str | None,
    ) -> tuple[Path | None, Path, GenerationMetrics | None]:
        """Run generation in container and export results."""
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

        # mount cache volume for python deps (safe for concurrent access)
        # note: npm cache is NOT cached to avoid corruption under parallel execution
        # npm packages are already optimized via BuildKit cache mounts in Dockerfile
        python_cache = client.cache_volume("klaudbiusz-python-cache")
        container = base_container.with_mounted_cache(
            "/home/klaudbiusz/.cache", python_cache, owner="klaudbiusz:klaudbiusz"
        )

        # run generation
        result = container.with_exec(cmd)

        # prepare log file path
        log_file_local = self.output_dir / "logs" / f"{app_name}.log"
        log_file_local.parent.mkdir(parents=True, exist_ok=True)

        # capture stdout/stderr - even on failure we want to save what we can
        try:
            log_content = await result.stdout()
            stderr_content = await result.stderr()
            full_log = f"{log_content}\n\n=== STDERR ===\n{stderr_content}" if stderr_content else log_content
            log_file_local.write_text(full_log)
        except dagger.ExecError as e:
            # container command failed - save error output as log
            full_log = f"=== EXEC ERROR ===\n{e}\n\n=== STDOUT ===\n{e.stdout}\n\n=== STDERR ===\n{e.stderr}"
            log_file_local.write_text(full_log)
            raise

        # export workspace and find app directory by generation_metrics.json
        workspace_local = self.output_dir / f".workspace-{app_name}"
        try:
            await result.directory("/workspace").export(str(workspace_local))
        except dagger.QueryError as e:
            if "no such file or directory" in str(e):
                return None, log_file_local, None
            raise

        # find app directory containing generation_metrics.json
        app_dir_local: Path | None = None
        for metrics_file in workspace_local.rglob("generation_metrics.json"):
            app_dir_local = metrics_file.parent
            break

        if app_dir_local is None:
            # no app created, clean up workspace
            shutil.rmtree(workspace_local, ignore_errors=True)
            return None, log_file_local, None

        # move app to final location and clean up
        final_app_dir = self.output_dir / app_dir_local.name
        if final_app_dir.exists():
            shutil.rmtree(final_app_dir)
        app_dir_local.rename(final_app_dir)
        shutil.rmtree(workspace_local, ignore_errors=True)

        metrics = _read_metrics_from_app(final_app_dir)
        return final_app_dir, log_file_local, metrics

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
            backend: "claude" or "litellm"
            model: model name (required for litellm)
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

            async def run_with_sem(
                app_name: str, prompt: str
            ) -> tuple[str, Path | None, Path | None, GenerationMetrics | None, str | None]:
                async with sem:
                    try:
                        app_dir, log_file, metrics = await self._run_generation(
                            client, base_container, prompt, app_name, backend, model
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

    async def _build_container(self, client: dagger.Client) -> dagger.Container:
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

        # mount skill directory for Claude Code skills
        container = container.with_directory(
            "/workspace/.claude/skills/databricks-apps",
            client.host().directory(str(self.skill_path)),
            owner="klaudbiusz:klaudbiusz",
        )

        # mount databricks binary and add to PATH
        container = container.with_file(
            "/usr/local/bin/databricks",
            client.host().file(str(self.databricks_binary)),
            permissions=0o755,
        )

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

        # mount databricks directory for OAuth token cache and other CLI state
        # required when using auth_type = databricks-cli
        databricks_dir = Path.home() / ".databricks"
        if databricks_dir.exists():
            container = container.with_directory(
                "/home/klaudbiusz/.databricks",
                client.host().directory(str(databricks_dir)),
                owner="klaudbiusz:klaudbiusz",
            )

        return container
