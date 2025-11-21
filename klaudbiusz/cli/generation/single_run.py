import fire
from datetime import datetime
from dotenv import load_dotenv

from cli.generation.codegen import ClaudeAppBuilder, GenerationMetrics as ClaudeGenerationMetrics
from cli.generation.codegen_multi import LiteLLMAppBuilder

# Load environment variables from .env file
load_dotenv()


def run(
    prompt: str,
    app_name: str | None = None,
    backend: str = "claude",
    model: str | None = None,
    wipe_db: bool = True,
    use_subagents: bool = False,
    mcp_binary: str | None = None,
    mcp_json: str | None = None,
):
    """Run app builder with given prompt.

    Args:
        prompt: The prompt describing what to build
        app_name: Optional app name (default: timestamp-based)
        backend: Backend to use ("claude" or "litellm", default: "claude")
        model: LLM model (required if backend=litellm, e.g., "openrouter/minimax/minimax-m2")
        wipe_db: Whether to wipe database on start
        use_subagents: Whether to enable subagent delegation (claude backend only)
        mcp_binary: Optional path to pre-built edda-mcp binary (default: use cargo run)
        mcp_json: Optional path to JSON config file for edda_mcp

    Usage:
        # Claude backend (default)
        python main.py "build dashboard" --use_subagents
        python main.py "build dashboard" --app_name=my-dashboard

        # LiteLLM backend
        python main.py "build dashboard" --backend=litellm --model=openrouter/minimax/minimax-m2
        python main.py "build dashboard" --backend=litellm --model=gemini/gemini-2.5-pro

        # Custom MCP config
        python main.py "build dashboard" --mcp_json=./config/databricks-cli.json
    """
    if app_name is None:
        app_name = f"app-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # single run always shows logs
    suppress_logs = False

    match backend:
        case "claude":
            builder = ClaudeAppBuilder(
                app_name=app_name,
                wipe_db=wipe_db,
                suppress_logs=suppress_logs,
                use_subagents=use_subagents,
                mcp_binary=mcp_binary,
                mcp_json_path=mcp_json,
            )
            metrics = builder.run(prompt, wipe_db=wipe_db)
        case "litellm":
            if not model:
                raise ValueError("--model is required when using --backend=litellm")
            builder_litellm = LiteLLMAppBuilder(
                app_name=app_name,
                model=model,
                mcp_binary=mcp_binary,
                mcp_json_path=mcp_json,
                suppress_logs=suppress_logs,
            )
            litellm_metrics = builder_litellm.run(prompt)
            # convert to dict format for consistent output
            metrics: ClaudeGenerationMetrics = {
                "cost_usd": litellm_metrics.cost_usd,
                "input_tokens": litellm_metrics.input_tokens,
                "output_tokens": litellm_metrics.output_tokens,
                "turns": litellm_metrics.turns,
                "app_dir": litellm_metrics.app_dir,
            }
        case _:
            raise ValueError(f"Unknown backend: {backend}. Use 'claude' or 'litellm'")

    if metrics:
        print(f"\n{'=' * 80}")
        print("Final metrics:")
        print(f"  Cost: ${metrics['cost_usd']:.4f}")
        print(f"  Turns: {metrics['turns']}")
        print(f"  App dir: {metrics.get('app_dir', 'NOT CAPTURED')}")
        print(f"{'=' * 80}\n")
    return metrics


def main():
    fire.Fire(run)


if __name__ == "__main__":
    main()
