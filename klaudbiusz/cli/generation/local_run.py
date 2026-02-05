"""Single app generation without Dagger (runs locally)."""

from datetime import datetime
from pathlib import Path

import fire
from dotenv import load_dotenv

from cli.generation.codegen import ClaudeAppBuilder

load_dotenv()


def run(
    prompt: str,
    app_name: str | None = None,
    output_dir: str | None = None,
    model: str | None = None,
) -> dict[str, str | None]:
    """Run app generation locally (no Dagger).

    Note: Only Claude backend is supported for local runs.
    For OpenCode, use single_run.py with Dagger.

    Args:
        prompt: The prompt describing what to build
        app_name: Optional app name (default: timestamp-based)
        output_dir: Directory to store generated apps (default: ./app)
        model: LLM model (e.g. "openrouter/moonshotai/kimi-k2.5")

    Usage:
        uv run python -m cli.generation.local_run "build dashboard"
        uv run python -m cli.generation.local_run "build dashboard" --model="openrouter/moonshotai/kimi-k2.5"
    """
    if app_name is None:
        app_name = f"app-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    resolved_output_dir = Path(output_dir) if output_dir else Path("./app")

    builder = ClaudeAppBuilder(
        app_name=app_name,
        output_dir=str(resolved_output_dir),
        model=model,
    )
    metrics = builder.run(prompt)
    app_dir = metrics.get("app_dir")

    print(f"\n{'=' * 80}")
    if app_dir:
        print("Generation complete:")
        print(f"  App: {app_dir}")
    else:
        print("No app generated (agent may have just answered without creating files)")
    print(f"{'=' * 80}\n")

    return {"app_dir": app_dir}



if __name__ == "__main__":
    fire.Fire(run)
