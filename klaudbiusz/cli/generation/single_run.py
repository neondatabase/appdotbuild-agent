"""Single app generation via Dagger."""

import asyncio
import os
from datetime import datetime
from pathlib import Path

import fire
from dotenv import load_dotenv

from cli.generation.dagger_run import DaggerAppGenerator

load_dotenv()


def _restore_terminal_cursor() -> None:
    """Restore terminal cursor after Dagger run (workaround for dagger/dagger#7160)."""
    os.system("tput cnorm 2>/dev/null || true")


def run(
    prompt: str,
    app_name: str | None = None,
    backend: str = "claude",
    model: str | None = None,
    output_dir: str | None = None,
) -> dict[str, str | None]:
    """Run app generation in Dagger container.

    Args:
        prompt: The prompt describing what to build
        app_name: Optional app name (default: timestamp-based)
        backend: Backend to use ("claude" or "opencode", default: "claude")
        model: LLM model (optional, for opencode non-default model)
        output_dir: Directory to store generated apps (default: ./app)

    Usage:
        # Claude backend (default) - uses skills
        python single_run.py "build dashboard"

        # OpenCode backend - uses skills
        python single_run.py "build dashboard" --backend=opencode

        # OpenCode with custom model
        python single_run.py "build dashboard" --backend=opencode --model=anthropic/claude-opus-4-5-20251101
    """
    if app_name is None:
        app_name = f"app-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    generator = DaggerAppGenerator(
        output_dir=Path(output_dir) if output_dir else Path("./app"),
    )

    try:
        app_dir, log_file, metrics = asyncio.run(
            generator.generate_single(prompt, app_name, backend, model)
        )
    finally:
        _restore_terminal_cursor()

    print(f"\n{'=' * 80}")
    if app_dir:
        print("Generation complete:")
        print(f"  App: {app_dir}")
    else:
        print("No app generated (agent may have just answered without creating files)")
    print(f"  Log: {log_file}")
    if metrics:
        print(f"  Cost: ${metrics['cost_usd']:.4f} ({metrics['input_tokens']} in / {metrics['output_tokens']} out)")
    print(f"{'=' * 80}\n")

    return {"app_dir": str(app_dir) if app_dir else None, "log_file": str(log_file)}


def main():
    fire.Fire(run)


if __name__ == "__main__":
    main()
