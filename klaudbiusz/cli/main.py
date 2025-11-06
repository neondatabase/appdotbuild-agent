import fire
from datetime import datetime
from dotenv import load_dotenv

from codegen import AppBuilder

# Load environment variables from .env file
load_dotenv()


def run(prompt: str, app_name: str | None = None, wipe_db: bool = True, suppress_logs: bool = False, use_subagents: bool = False, mcp_binary: str | None = None, io_config: str | None = None):
    """Run app builder with given prompt.

    Args:
        prompt: The prompt describing what to build
        app_name: Optional app name (default: timestamp-based)
        wipe_db: Whether to wipe database on start
        suppress_logs: Whether to suppress logs
        use_subagents: Whether to enable subagent delegation (e.g., dataresearch)
        mcp_binary: Optional path to pre-built edda-mcp binary (default: use cargo run)
        io_config: Optional JSON string for IO config (e.g., '{"template":{"Custom":{"name":"sdk","path":"/path/to/template"}}}')

    Usage:
        python main.py "your prompt here" --use_subagents
        python main.py "build dashboard" --app_name=my-dashboard --use_subagents
        python main.py "build dashboard" --use_subagents --no-wipe_db
        python main.py "build dashboard" --mcp_binary=/path/to/edda-mcp
        python main.py "build dashboard" --io_config='{"template":{"Custom":{"name":"sdk","path":"/path"}}}'
    """
    if app_name is None:
        app_name = f"app-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # build mcp_extra_args from io_config
    # Fire might parse JSON strings as dicts, so ensure it's a string
    mcp_extra_args = []
    if io_config:
        import json
        io_config_str = io_config if isinstance(io_config, str) else json.dumps(io_config)
        mcp_extra_args.extend(["--io-config", io_config_str])

    builder = AppBuilder(app_name=app_name, wipe_db=wipe_db, suppress_logs=suppress_logs, use_subagents=use_subagents, mcp_binary=mcp_binary, mcp_extra_args=mcp_extra_args)
    metrics = builder.run(prompt, wipe_db=wipe_db)
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
