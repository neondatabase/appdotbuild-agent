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
    mcp_binary: str | None = None,
    mcp_args: list[str] | None = None,
    output_dir: str | None = None,
) -> dict[str, str | None]:
    """Run app generation in Dagger container.

    Args:
        prompt: The prompt describing what to build
        app_name: Optional app name (default: timestamp-based)
        backend: Backend to use ("claude", "opencode", or "litellm", default: "claude")
        model: LLM model (required if backend=litellm)
        mcp_binary: Path to edda_mcp binary (required for litellm backend)
        mcp_args: Optional list of args passed to the MCP server (litellm only)
        output_dir: Directory to store generated apps (default: ./app)

    Usage:
        # Claude backend (default) - uses skills, no MCP needed
        python single_run.py "build dashboard"

        # OpenCode backend - uses skills, no MCP needed
        python single_run.py "build dashboard" --backend=opencode

        # LiteLLM backend (requires MCP)
        python single_run.py "build dashboard" --backend=litellm --model=gemini/gemini-2.5-pro --mcp_binary=/path/to/edda_mcp
    """
    if backend == "litellm":
        if not model:
            raise ValueError("--model is required when using --backend=litellm")
        if not mcp_binary:
            raise ValueError("--mcp_binary is required for litellm backend")

    if app_name is None:
        app_name = f"app-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    generator = DaggerAppGenerator(
        output_dir=Path(output_dir) if output_dir else Path("./app"),
        mcp_binary=Path(mcp_binary) if mcp_binary else None,
    )

    try:
        app_dir, log_file, metrics = asyncio.run(
            generator.generate_single(prompt, app_name, backend, model, mcp_args)
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
