"""Run GEPA optimization experiment for Databricks CLI agent.

This script optimizes the Databricks MCP tool descriptions and CLAUDE.md template
to improve agent performance on generating Databricks apps.
"""

import argparse

from gepa import optimize, NoImprovementStopper

from databricks import DatabricksAdapter, Task, CANDIDATE_KEYS
from experiments.dataset import PROMPTS


def create_tasks(prompt_keys: list[str] | None = None) -> list[Task]:
    """Create tasks from the Databricks prompts dataset."""
    if prompt_keys is None:
        prompt_keys = list(PROMPTS.keys())

    return [Task(prompt=PROMPTS[key]) for key in prompt_keys if key in PROMPTS]


def get_training_tasks() -> list[Task]:
    """Get training set tasks (first 15 prompts)."""
    keys = list(PROMPTS.keys())[:15]
    return create_tasks(keys)


def get_validation_tasks() -> list[Task]:
    """Get validation set tasks (remaining prompts)."""
    keys = list(PROMPTS.keys())[15:]
    return create_tasks(keys)


def get_quick_test_tasks() -> list[Task]:
    """Get a small subset for quick testing."""
    keys = list(PROMPTS.keys())[:5]
    return create_tasks(keys)


def run_quick_test():
    """Run a quick test with minimal tasks."""
    print("Running quick Databricks optimization test...")
    print("=" * 60)

    adapter = DatabricksAdapter()

    # Load seed candidate from CLI repository
    print("Loading seed candidate from Databricks CLI repository...")
    seed_candidate = adapter.load_seed_candidate()
    print(f"Loaded {len(seed_candidate)} candidate components:")
    for key in seed_candidate:
        preview = seed_candidate[key][:100] + "..." if len(seed_candidate[key]) > 100 else seed_candidate[key]
        print(f"  - {key}: {preview}")

    tasks = get_quick_test_tasks()
    trainset = tasks[:3]
    valset = tasks[3:]

    print(f"\nTraining tasks: {len(trainset)}")
    print(f"Validation tasks: {len(valset)}")
    print("=" * 60)

    result = optimize(
        seed_candidate=seed_candidate,
        trainset=trainset,
        valset=valset,
        adapter=adapter,
        reflection_lm="claude-opus-4-5-20251101",
        max_metric_calls=10,
        reflection_minibatch_size=2,
        run_dir="./runs/databricks_quick_test",
        display_progress_bar=True,
        seed=42,
    )

    print("\n" + "=" * 60)
    print("Optimization complete!")
    print("=" * 60)
    print("\nBest candidate components:")
    for key in CANDIDATE_KEYS:
        if key in result.best_candidate:
            value = result.best_candidate[key]
            preview = value[:200] + "..." if len(value) > 200 else value
            print(f"\n{key}:\n{preview}")

    return result


def run_full_optimization():
    """Run full optimization with all tasks."""
    print("Running full Databricks optimization...")
    print("=" * 60)

    adapter = DatabricksAdapter()

    # Load seed candidate from CLI repository
    print("Loading seed candidate from Databricks CLI repository...")
    seed_candidate = adapter.load_seed_candidate()
    print(f"Loaded {len(seed_candidate)} candidate components")

    trainset = get_training_tasks()
    valset = get_validation_tasks()

    print(f"\nTraining tasks: {len(trainset)}")
    print(f"Validation tasks: {len(valset)}")
    print("=" * 60)

    result = optimize(
        seed_candidate=seed_candidate,
        trainset=trainset,
        valset=valset,
        adapter=adapter,
        reflection_lm="claude-opus-4-5-20251101",
        max_metric_calls=100,
        reflection_minibatch_size=3,
        stop_callbacks=[
            NoImprovementStopper(max_iterations_without_improvement=10),
        ],
        run_dir="./runs/databricks_full_optimization",
        display_progress_bar=True,
        seed=42,
    )

    print("\n" + "=" * 60)
    print("Optimization complete!")
    print("=" * 60)
    print("\nBest candidate components:")
    for key in CANDIDATE_KEYS:
        if key in result.best_candidate:
            value = result.best_candidate[key]
            preview = value[:200] + "..." if len(value) > 200 else value
            print(f"\n{key}:\n{preview}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run GEPA optimization for Databricks CLI agent"
    )
    parser.add_argument(
        "--mode",
        choices=["quick", "full"],
        default="quick",
        help="Run mode: quick test or full optimization",
    )
    args = parser.parse_args()

    if args.mode == "quick":
        run_quick_test()
    else:
        run_full_optimization()


if __name__ == "__main__":
    main()
