"""Single app generation without Dagger (runs locally)."""

from datetime import datetime
from pathlib import Path

import fire
from dotenv import load_dotenv

from cli.generation.codegen import ClaudeAppBuilder
from cli.generation.codegen_multi import LiteLLMAppBuilder

load_dotenv()


def run(
    prompt: str,
    app_name: str | None = None,
    backend: str = "claude",
    model: str | None = None,
    mcp_binary: str | None = None,
    mcp_args: list[str] | None = None,
    output_dir: str | None = None,
) -> dict[str, str | None]:
    """Run app generation locally (no Dagger).

    Args:
        prompt: The prompt describing what to build
        app_name: Optional app name (default: timestamp-based)
        backend: Backend to use ("claude" or "litellm", default: "claude")
        model: LLM model (required if backend=litellm)
        mcp_binary: Path to edda_mcp binary (required for litellm backend)
        mcp_args: Optional list of args passed to the MCP server (litellm only)
        output_dir: Directory to store generated apps (default: ./app)

    Usage:
        # Claude backend (default) - uses skills, no MCP needed
        uv run python -m cli.generation.local_run "build dashboard"

        # LiteLLM backend - still requires MCP
        uv run python -m cli.generation.local_run "build dashboard" --backend=litellm --model=gemini/gemini-2.5-pro --mcp_binary=/path/to/edda_mcp
    """
    if backend == "litellm":
        if not model:
            raise ValueError("--model is required when using --backend=litellm")
        if not mcp_binary:
            raise ValueError("--mcp_binary is required for litellm backend")

    if app_name is None:
        app_name = f"app-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    resolved_output_dir = Path(output_dir) if output_dir else Path("./app")

    match backend:
        case "claude":
            builder = ClaudeAppBuilder(
                app_name=app_name,
                output_dir=str(resolved_output_dir),
            )
            metrics = builder.run(prompt)
            app_dir = metrics.get("app_dir")
        case "litellm":
            assert model is not None  # already validated above
            builder = LiteLLMAppBuilder(
                app_name=app_name,
                model=model,
                mcp_binary=mcp_binary,
                mcp_args=mcp_args,
                output_dir=str(resolved_output_dir),
            )
            result = builder.run(prompt)
            app_dir = result.app_dir
        case _:
            raise ValueError(f"Unknown backend: {backend}. Use 'claude' or 'litellm'.")

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
