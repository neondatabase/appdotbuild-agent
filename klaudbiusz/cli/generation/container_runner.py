"""Runner script executed inside Dagger container."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import fire

# directories that exist in /workspace before generation (source code)
_KNOWN_DIRS = {"cli", "__pycache__", ".venv"}


def _move_to_expected(actual_dir: Path, expected: Path, app_name: str) -> Path:
    """Move agent-created dir into expected path, merging if expected already exists."""
    print(f"Agent created '{actual_dir.name}' instead of '{app_name}', moving to '{expected}'")
    shutil.copytree(actual_dir, expected, dirs_exist_ok=True)
    shutil.rmtree(actual_dir)
    return expected


def _find_new_app_dir(output_dir: Path, app_name: str, pre_existing: set[str]) -> Path | None:
    """Find the app directory the agent actually created.

    Compares current top-level dirs against pre-existing snapshot.
    If the agent created a dir with a different name, move it to expected app_name.
    """
    expected = output_dir / app_name

    # find new directories created during generation
    current_dirs = {d.name for d in output_dir.iterdir() if d.is_dir()}
    new_dirs = current_dirs - pre_existing - _KNOWN_DIRS - {app_name}
    # filter out empty dirs
    new_dirs = {d for d in new_dirs if any((output_dir / d).iterdir())}

    if not new_dirs:
        # agent used the expected name (or created nothing)
        if expected.exists() and any(expected.iterdir()):
            return expected
        return None

    if len(new_dirs) == 1:
        return _move_to_expected(output_dir / new_dirs.pop(), expected, app_name)

    # multiple new dirs — pick the one with a databricks.yml or package.json
    for marker in ("databricks.yml", "package.json"):
        for d in new_dirs:
            if (output_dir / d / marker).exists():
                return _move_to_expected(output_dir / d, expected, app_name)

    # last resort: pick the largest new directory
    largest = max(new_dirs, key=lambda d: sum(1 for _ in (output_dir / d).rglob("*")))
    return _move_to_expected(output_dir / largest, expected, app_name)


def run(
    prompt: str,
    app_name: str,
    backend: str = "claude",
    model: str | None = None,
    output_dir: str = "/workspace",
) -> None:
    """Run app generation (inside container or locally for debugging).

    Args:
        prompt: The prompt describing what to build
        app_name: App name for output directory
        backend: "claude" or "opencode"
        model: Model name (optional, for opencode non-default model)
        output_dir: Output directory for generated app (default: /workspace for container)
    """
    out_path = Path(output_dir)

    # snapshot existing directories before generation
    pre_existing = {d.name for d in out_path.iterdir() if d.is_dir()}

    metrics = None
    error: Exception | None = None

    match backend:
        case "claude":
            from cli.generation.codegen import ClaudeAppBuilder

            builder = ClaudeAppBuilder(
                app_name=app_name,
                wipe_db=False,
                suppress_logs=False,
                output_dir=output_dir,
                model=model,
            )
            try:
                metrics = builder.run(prompt, wipe_db=False)
            except Exception as e:
                error = e
        case "opencode":
            metrics = _run_opencode(
                prompt=prompt,
                app_name=app_name,
                model=model,
                output_dir=output_dir,
            )
        case _:
            print(f"Error: Unknown backend: {backend}", file=sys.stderr)
            sys.exit(1)

    # find and normalize the app directory (rename if agent used different name)
    app_dir = _find_new_app_dir(out_path, app_name, pre_existing)

    if error:
        print(f"SDK error: {error}", file=sys.stderr)
        if app_dir:
            print(f"App directory exists at {app_dir}, treating as success despite SDK error")
        else:
            sys.exit(1)

    print(f"Metrics: {metrics}")


def _run_opencode(
    prompt: str,
    app_name: str,
    model: str | None,
    output_dir: str,
) -> dict:
    """Run opencode generation via bun subprocess."""
    # build command
    cmd = [
        "bun",
        "run",
        "cli/generation_opencode/src/index.ts",
        "--app-name",
        app_name,
        "--prompt",
        prompt,
        "--output-dir",
        output_dir,
    ]

    if model:
        cmd.extend(["--model", model])

    # run opencode generation
    result = subprocess.run(cmd, cwd="/workspace", capture_output=False)

    if result.returncode != 0:
        print(f"Error: opencode generation failed with code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)

    # read metrics from generated file
    metrics_file = Path(output_dir) / app_name / "generation_metrics.json"
    if metrics_file.exists():
        return json.loads(metrics_file.read_text())

    return {"cost_usd": 0, "input_tokens": 0, "output_tokens": 0, "turns": 0}


if __name__ == "__main__":
    fire.Fire(run)
