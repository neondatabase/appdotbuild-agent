#!/usr/bin/env python3
"""Three-agent skill evolution system.

Runs an outer loop: Builder -> Grader -> Engineer -> repeat
Each agent uses a skill to perform its task.
"""
import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path

from config import EvolutionConfig
from agents import run_builder, run_grader_single, run_engineer, BuildResult, GradeResult
from prompts import PROMPTS


async def run_evolution(config: EvolutionConfig) -> Path:
    """Run the evolution loop.

    Returns path to run directory with all artifacts.
    """
    run_dir = config.output_dir / f"run-{datetime.now():%Y%m%d_%H%M%S}"
    run_dir.mkdir(parents=True)

    # save config
    config_data = {
        "skills_dir": str(config.skills_dir),
        "output_dir": str(config.output_dir),
        "num_iterations": config.num_iterations,
        "prompts_per_iteration": config.prompts_per_iteration,
        "model": config.model,
        "max_turns": config.max_turns,
        "prompts": config.prompts,
    }
    (run_dir / "config.json").write_text(json.dumps(config_data, indent=2))

    # snapshot initial webapp-creation skill as v0
    skill_versions = run_dir / "skill-versions"
    skill_versions.mkdir()
    original_skill = config.skills_dir / "webapp-creation"
    current_skill_version = skill_versions / "v0"
    shutil.copytree(original_skill, current_skill_version)

    # working skill dir - the evolving webapp-creation skill
    working_skill = run_dir / "working-skill"
    working_skill.mkdir(parents=True)
    shutil.copytree(current_skill_version, working_skill / "webapp-creation")
    print(f"Working skill: {working_skill / 'webapp-creation'}")

    prompt_list = list(config.prompts.items())
    metrics: list[dict] = []

    for i in range(config.num_iterations):
        print(f"\n{'='*60}")
        print(f"ITERATION {i+1}/{config.num_iterations}")
        print(f"{'='*60}")

        iter_dir = run_dir / f"iterations/iter-{i}"
        iter_dir.mkdir(parents=True)
        apps_dir = iter_dir / "apps"
        apps_dir.mkdir()

        # select prompts for this iteration
        selected = prompt_list[:config.prompts_per_iteration]

        # 1. BUILD all apps concurrently
        print(f"\n[BUILD] Building {len(selected)} apps concurrently...")

        build_tasks = [
            run_builder(
                prompt=prompt,
                app_name=name,
                output_dir=apps_dir,
                webapp_creation_skill=working_skill / "webapp-creation",
                model=config.model,
                max_turns=config.max_turns,
                verbose=config.verbose,
            )
            for name, prompt in selected
        ]

        build_results: list[BuildResult] = await asyncio.gather(*build_tasks)

        # print build results
        app_dirs: list[Path] = []
        traj_paths: list[Path] = []

        for result in build_results:
            print(f"\n  [{result.app_name}]")
            if config.verbose:
                result.print_logs()
            if result.success and result.app_dir and result.trajectory_path:
                app_dirs.append(result.app_dir)
                traj_paths.append(result.trajectory_path)
                print(f"    -> OK")
            else:
                print(f"    -> FAILED")

        print(f"\n  Built {len(app_dirs)}/{len(selected)} apps successfully")

        # 2. GRADE all successful apps concurrently
        feedback_reports: list[dict] = []

        if app_dirs:
            print(f"\n[GRADE] Grading {len(app_dirs)} apps concurrently...")

            grade_tasks = [
                run_grader_single(
                    app_dir=app_dir,
                    traj_path=traj_path,
                    grading_skill=config.skills_dir / "webapp-grading",
                    model=config.model,
                    max_turns=config.max_turns,
                    verbose=config.verbose,
                )
                for app_dir, traj_path in zip(app_dirs, traj_paths)
            ]

            grade_results: list[GradeResult] = await asyncio.gather(*grade_tasks)

            # print grade results
            for result in grade_results:
                print(f"\n  [{result.app_name}]")
                if config.verbose:
                    result.print_logs()
                score = result.feedback.get("score", 0)
                print(f"    -> {score:.1f}/10")
                feedback_reports.append(result.feedback)

            (iter_dir / "feedback.json").write_text(json.dumps(feedback_reports, indent=2))

            scores = [r.get("score", 0) for r in feedback_reports]
            avg_score = sum(scores) / len(scores) if scores else 0
            print(f"\n  Average score: {avg_score:.1f}/10")

            iter_metrics = {
                "iteration": i,
                "apps_built": len(app_dirs),
                "apps_attempted": len(selected),
                "avg_score": avg_score,
                "scores": scores,
            }
            metrics.append(iter_metrics)
        else:
            print("\n[GRADE] No apps to grade")
            metrics.append({"iteration": i, "apps_built": 0, "apps_attempted": len(selected)})

        # 3. ENGINEER (except last iteration)
        if i < config.num_iterations - 1 and feedback_reports:
            print(f"\n[ENGINEER] Improving skill...")
            success = await run_engineer(
                feedback_reports=feedback_reports,
                webapp_creation_skill=working_skill / "webapp-creation",
                improver_skill=config.skills_dir / "skill-improver",
                run_dir=run_dir,
                model=config.model,
                max_turns=config.max_turns,
                verbose=config.verbose,
            )
            if success:
                print("  Skill updated")
                # snapshot new version
                next_skill = skill_versions / f"v{i+1}"
                shutil.copytree(working_skill / "webapp-creation", next_skill)
            else:
                print("  Engineer failed to update skill")

    # save summary
    summary = {
        "num_iterations": config.num_iterations,
        "metrics": metrics,
        "final_skill_version": f"v{config.num_iterations - 1}",
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n{'='*60}")
    print("EVOLUTION COMPLETE")
    print(f"{'='*60}")
    print(f"Results: {run_dir}")

    return run_dir


def main():
    import fire

    def evolve(
        num_iterations: int = 3,
        prompts_per_iteration: int = 3,
        model: str = "claude-sonnet-4-5-20250929",
        max_turns: int = 50,
        verbose: bool = False,
    ):
        """Run skill evolution loop.

        Args:
            num_iterations: Number of evolution cycles
            prompts_per_iteration: Apps to build per cycle
            model: Claude model to use
            max_turns: Max turns per agent
            verbose: Show detailed agent progress (tools, turns, costs)
        """
        base = Path(__file__).parent
        config = EvolutionConfig(
            skills_dir=base / "skills",
            output_dir=base / "runs",
            num_iterations=num_iterations,
            prompts_per_iteration=prompts_per_iteration,
            model=model,
            max_turns=max_turns,
            prompts=PROMPTS,
            verbose=verbose,
        )

        print(f"Starting evolution with {num_iterations} iterations")
        print(f"Building {prompts_per_iteration} apps per iteration")
        print(f"Model: {model}")
        if verbose:
            print("Verbose mode: ON")

        asyncio.run(run_evolution(config))

    fire.Fire(evolve)


if __name__ == "__main__":
    main()
