"""Async GEPA adapter."""

from typing import Any, Protocol, TypeVar

from anyio.from_thread import start_blocking_portal
from gepa.core.adapter import EvaluationBatch, ProposalFn

RolloutOutput = TypeVar("RolloutOutput")
Trajectory = TypeVar("Trajectory")
DataInst = TypeVar("DataInst")


class AsyncGEPA(Protocol[DataInst, Trajectory, RolloutOutput]):
    """Base GEPA adapter for optimizing Claude agents."""

    propose_new_texts: ProposalFn | None = None

    def evaluate(
        self,
        batch: list[DataInst],
        candidate: dict[str, str],
        capture_traces: bool = False,
    ) -> EvaluationBatch[Trajectory, RolloutOutput]:
        """Execute agent on batch and return scores with optional trajectories."""
        with start_blocking_portal() as portal:
            return portal.call(self._evaluate_async, batch, candidate, capture_traces)

    async def _evaluate_async(
        self,
        batch: list[DataInst],
        candidate: dict[str, str],
        capture_traces: bool = False,
    ) -> EvaluationBatch[Trajectory, RolloutOutput]:
        """Internal async implementation of evaluate."""
        ...

    def make_reflective_dataset(
        self,
        candidate: dict[str, str],
        eval_batch: EvaluationBatch[Trajectory, RolloutOutput],
        components_to_update: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Create reflective dataset from evaluation results."""
        ...
