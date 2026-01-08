"""GEPA adapter for Databricks CLI agent optimization."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anyio import create_task_group
from gepa.core.adapter import EvaluationBatch
from optimizer.adapter import AsyncGEPA
from sbclient.client import ClaudeClient, DockerConfig
from sbclaude.schema import (
    MessageModel,
    EvtInterruptModel,
    EvtResultModel,
    EvtErrorModel,
)

from .bundle import CliBundle
from .patch import CliPatchData, load_patch_data, apply_patch
from .metrics import MetricResult, compute_composite_score, build_reflection_context, evaluate_trajectory


# Candidate keys that map to CliPatchData fields
CANDIDATE_KEYS = [
    "template_claude_md",
    "invoke_cli_description",
    "discover_description",
    "configure_auth_description",
]


@dataclass
class Task:
    """Input task for the agent."""
    prompt: str


@dataclass
class Trajectory:
    """Agent execution trajectory."""
    task: Task
    messages: list[MessageModel]
    metrics: dict[str, MetricResult] = field(default_factory=dict)


@dataclass
class Output:
    """Agent execution output."""
    completed: bool
    error: str | None = None


@dataclass
class AdapterConfig:
    """Configuration for Adapter."""
    cli_repo_url: str = "https://github.com/databricks/cli"
    cli_branch: str = "main"
    dockerfile_path: Path = field(default_factory=lambda: Path("Dockerfile"))
    build_context: Path = field(default_factory=lambda: Path("."))
    databrickscfg_path: Path = field(default_factory=lambda: Path.home() / ".databrickscfg")
    databricks_oauth_path: Path = field(default_factory=lambda: Path.home() / ".databricks")


class DatabricksAdapter(AsyncGEPA[Task, Trajectory, Output]):
    """GEPA adapter for optimizing Databricks CLI agent prompts."""

    def __init__(self, config: AdapterConfig = AdapterConfig()):
        self.config = config

    def load_seed_candidate(self) -> dict[str, str]:
        """Load the seed candidate from the CLI repository.

        Returns a dict with the current tool descriptions and template.
        """
        bundle = CliBundle(self.config.cli_repo_url, self.config.cli_branch)
        patch_data = load_patch_data(bundle)

        candidate: dict[str, str] = {}
        for key in CANDIDATE_KEYS:
            value = getattr(patch_data, key)
            if value is not None:
                candidate[key] = value

        return candidate

    def _build_cli_with_candidate(self, candidate: dict[str, str]) -> tuple[CliBundle, Path]:
        """Build the CLI with patches from the candidate applied."""
        bundle = CliBundle(self.config.cli_repo_url, self.config.cli_branch)

        patch_data = CliPatchData(
            template_claude_md=candidate.get("template_claude_md"),
            invoke_cli_description=candidate.get("invoke_cli_description"),
            discover_description=candidate.get("discover_description"),
            configure_auth_description=candidate.get("configure_auth_description"),
        )

        apply_patch(bundle, patch_data)
        bundle.build()

        return bundle, bundle.tmp_dir / "cli"

    async def _evaluate_async(
        self,
        batch: list[Task],
        candidate: dict[str, str],
        capture_traces: bool = False,
    ) -> EvaluationBatch[Trajectory, Output]:
        """Internal async implementation of evaluate."""
        results: dict[int, tuple[Output, float, Trajectory]] = {}

        _bundle, cli_path = self._build_cli_with_candidate(candidate)

        docker_config = DockerConfig(
            dockerfile_path=self.config.dockerfile_path,
            build_context=self.config.build_context,
            environment={"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")},
            mounted_dirs={
                self.config.databrickscfg_path: Path("/home/sbclaude/.databrickscfg"),
                self.config.databricks_oauth_path: Path("/home/sbclaude/.databricks"),
                cli_path: Path("/usr/local/bin/databricks"),
            },
        )

        prompt_config = {
            "mcp_servers": {
                "databricks": {
                    "type": "stdio",
                    "command": "databricks",
                    "args": ["experimental", "apps-mcp"],
                    "env": {},
                }
            }
        }

        async def _run_task(idx: int, task: Task):
            trajectory = Trajectory(task=task, messages=[])
            output = Output(completed=False)
            score = 0.0

            async with ClaudeClient(config=docker_config) as client:
                async for event in client.prompt(task.prompt, config=prompt_config):
                    if isinstance(event, EvtInterruptModel):
                        trajectory.messages = event.messages
                        await client.continue_()
                    elif isinstance(event, EvtResultModel):
                        trajectory.messages = event.messages
                        output.completed = True
                        break
                    elif isinstance(event, EvtErrorModel):
                        raise RuntimeError(event.detail)

                trajectory.metrics = evaluate_trajectory(trajectory.messages)
                score = compute_composite_score(trajectory.metrics)

            results[idx] = (output, score, trajectory)

        async with create_task_group() as tg:
            for idx, task in enumerate(batch):
                tg.start_soon(_run_task, idx, task)

        outputs = list(results.values())

        return EvaluationBatch(
            outputs=[r[0] for r in outputs],
            scores=[r[1] for r in outputs],
            trajectories=[r[2] for r in outputs] if capture_traces else None,
        )

    def make_reflective_dataset(
        self,
        candidate: dict[str, str],
        eval_batch: EvaluationBatch[Trajectory, Output],
        components_to_update: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Create reflective dataset from evaluation results."""
        if not eval_batch.trajectories:
            return {comp: [] for comp in components_to_update}

        dataset: dict[str, list[dict[str, Any]]] = {}

        examples = []
        for trajectory, score in zip(eval_batch.trajectories, eval_batch.scores):
            example: dict[str, Any] = {
                "Inputs": trajectory.task.prompt,
                "Feedback": build_reflection_context(trajectory.metrics),
            }
            examples.append(example)

        for component in components_to_update:
            dataset[component] = examples

        return dataset
