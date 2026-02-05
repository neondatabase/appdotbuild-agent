"""Runner script executed inside Dagger container."""

import json
import subprocess
import sys
from pathlib import Path

import fire


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

    # check if app was created even if SDK had an error
    app_dir = Path(output_dir) / app_name
    app_exists = app_dir.exists() and any(app_dir.iterdir())

    if error:
        print(f"SDK error: {error}", file=sys.stderr)
        if app_exists:
            # app was created before SDK error (e.g., shutdown bug) - treat as success
            print(f"App directory exists at {app_dir}, treating as success despite SDK error")
        else:
            # real failure - no app created
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
