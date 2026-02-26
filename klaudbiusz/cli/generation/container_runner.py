"""Runner script executed inside Dagger container."""

import json
import os
import signal
import shutil
import subprocess
import sys
from pathlib import Path

import fire

# directories that exist in /workspace before generation (source code)
_KNOWN_DIRS = {"cli", "__pycache__", ".venv"}
_HEAVY_DIRS_TO_PRUNE = {"node_modules", ".pnpm-store", ".yarn", ".next"}
_IGNORED_GENERATED_DIRS = {".pytest_cache", ".cache"}
OPENCODE_TIMEOUT_SEC = 30 * 60
OPENCODE_TIMEOUT_RETRIES = 1
OPENCODE_TERM_GRACE_SEC = 10
OPENCODE_KILL_GRACE_SEC = 5


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
    # filter out hidden/transient and empty dirs
    new_dirs = {
        d
        for d in new_dirs
        if not d.startswith(".")
        and d not in _IGNORED_GENERATED_DIRS
        and any((output_dir / d).iterdir())
    }

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


def _prune_heavy_artifacts(app_dir: Path) -> None:
    """Remove dependency/build directories to reduce Dagger snapshot size."""
    removed = 0
    for root, dirs, _ in os.walk(app_dir, topdown=True):
        prune_dirs = [d for d in dirs if d in _HEAVY_DIRS_TO_PRUNE]
        for dir_name in prune_dirs:
            shutil.rmtree(Path(root) / dir_name, ignore_errors=True)
            dirs.remove(dir_name)
            removed += 1

    if removed:
        print(f"Pruned {removed} heavy directories before export")


def _terminate_process_group(proc: subprocess.Popen) -> None:
    """Terminate spawned process group, then force kill if needed."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        proc.wait(timeout=OPENCODE_TERM_GRACE_SEC)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    proc.wait(timeout=OPENCODE_KILL_GRACE_SEC)


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
    if app_dir:
        _prune_heavy_artifacts(app_dir)

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

    # run opencode generation with hard timeout and one retry on timeout
    result_code: int | None = None
    for attempt in range(OPENCODE_TIMEOUT_RETRIES + 1):
        proc = subprocess.Popen(
            cmd,
            cwd="/workspace",
            start_new_session=True,  # allow killing whole process group on timeout
        )
        try:
            result_code = proc.wait(timeout=OPENCODE_TIMEOUT_SEC)
            break
        except subprocess.TimeoutExpired:
            _terminate_process_group(proc)
            if attempt < OPENCODE_TIMEOUT_RETRIES:
                print(
                    f"Warning: opencode timed out after {OPENCODE_TIMEOUT_SEC}s for '{app_name}', retrying once",
                    file=sys.stderr,
                )
                continue
            print(
                f"Error: opencode generation timed out after {OPENCODE_TIMEOUT_SEC}s for app '{app_name}'",
                file=sys.stderr,
            )
            sys.exit(124)

    assert result_code is not None
    if result_code != 0:
        print(f"Error: opencode generation failed with code {result_code}", file=sys.stderr)
        sys.exit(result_code)

    # read metrics from generated file
    metrics_file = Path(output_dir) / app_name / "generation_metrics.json"
    if metrics_file.exists():
        return json.loads(metrics_file.read_text())

    return {"cost_usd": 0, "input_tokens": 0, "output_tokens": 0, "turns": 0}


if __name__ == "__main__":
    fire.Fire(run)
