"""Bulk app generation via Dagger with parallelism."""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import fire
from dotenv import load_dotenv
from tqdm import tqdm

from cli.generation.dagger_run import DaggerAppGenerator

load_dotenv()


def _restore_terminal_cursor() -> None:
    """Restore terminal cursor after Dagger run (workaround for dagger/dagger#7160)."""
    os.system("tput cnorm 2>/dev/null || true")


def main(
    prompts: str = "databricks",
    backend: str = "claude",
    model: str | None = None,
    mcp_binary: str | None = None,
    mcp_args: list[str] | None = None,
    output_dir: str | None = None,
    max_concurrency: int = 6,
) -> None:
    """Bulk app generation via Dagger with parallelism.

    Args:
        prompts: Prompt set to use ("databricks", "databricks_v2", or "test")
        backend: Backend to use ("claude", "opencode", or "litellm")
        model: LLM model (required if backend=litellm)
        mcp_binary: Path to edda_mcp binary (required for litellm backend)
        mcp_args: Optional list of args passed to the MCP server (litellm only)
        output_dir: Custom output directory for generated apps
        max_concurrency: Maximum parallel generations (default: 6)

    Usage:
        # Claude backend with databricks prompts (uses skills, no MCP needed)
        python bulk_run.py

        # OpenCode backend (uses skills, no MCP needed)
        python bulk_run.py --backend=opencode

        # With custom concurrency
        python bulk_run.py --max_concurrency=8

        # LiteLLM backend (requires MCP)
        python bulk_run.py --backend=litellm --model=gemini/gemini-2.5-pro --mcp_binary=/path/to/edda_mcp
    """
    if backend == "litellm":
        if not model:
            raise ValueError("--model is required when using --backend=litellm")
        if not mcp_binary:
            raise ValueError("--mcp_binary is required for litellm backend")

    # load prompt set
    match prompts:
        case "databricks":
            from cli.generation.prompts.databricks import PROMPTS as selected_prompts
        case "databricks_v2":
            from cli.generation.prompts.databricks_v2 import PROMPTS as selected_prompts
        case "test":
            from cli.generation.prompts.web import PROMPTS as selected_prompts
        case _:
            raise ValueError(f"Unknown prompt set: {prompts}. Use 'databricks', 'databricks_v2', or 'test'")

    print(f"Starting bulk generation for {len(selected_prompts)} prompts...")
    print(f"Backend: {backend}")
    if backend == "litellm":
        print(f"Model: {model}")
        print(f"MCP binary: {mcp_binary}")
    print(f"Prompt set: {prompts}")
    print(f"Max concurrency: {max_concurrency}")
    out_path = Path(output_dir) if output_dir else Path("./app")
    print(f"Output dir: {out_path}\n")

    generator = DaggerAppGenerator(
        output_dir=out_path,
        mcp_binary=Path(mcp_binary) if mcp_binary else None,
        stream_logs=False,  # disable TUI for bulk runs
    )

    # progress bar with success/fail tracking
    pbar = tqdm(total=len(selected_prompts), desc="Generating apps", unit="app")
    success_count = 0
    fail_count = 0

    def on_complete(app_name: str, success: bool) -> None:
        nonlocal success_count, fail_count
        if success:
            success_count += 1
            status = "✓"
        else:
            fail_count += 1
            status = "✗"
        pbar.set_postfix(ok=success_count, fail=fail_count)
        pbar.set_description(f"{status} {app_name}")
        pbar.update(1)

    try:
        results = asyncio.run(
            generator.generate_bulk(
                selected_prompts,
                backend,
                model,
                mcp_args,
                max_concurrency,
                on_complete=on_complete,
            )
        )
    finally:
        pbar.close()
        _restore_terminal_cursor()

    # separate successful and failed (results now include metrics)
    successful = [(name, app_dir, log, metrics) for name, app_dir, log, metrics, err in results if err is None]
    failed = [(name, log, err) for name, app_dir, log, metrics, err in results if err is not None]

    # aggregate metrics from successful runs
    total_cost = 0.0
    total_tokens = 0
    total_turns = 0
    metrics_count = 0
    for _, _, _, metrics in successful:
        if metrics:
            total_cost += metrics.get("cost_usd", 0.0)
            total_tokens += metrics.get("input_tokens", 0)
            total_turns += metrics.get("turns", 0)
            metrics_count += 1

    print(f"\n{'=' * 80}")
    print("Bulk Generation Summary")
    print(f"{'=' * 80}")
    print(f"Total prompts: {len(selected_prompts)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")

    if metrics_count > 0:
        print(f"\nMetrics (from {metrics_count} runs):")
        print(f"  Total cost: ${total_cost:.4f}")
        print(f"  Avg cost: ${total_cost / metrics_count:.4f}")
        print(f"  Total tokens: {total_tokens:,}")
        print(f"  Avg tokens: {total_tokens // metrics_count:,}")
        print(f"  Avg turns: {total_turns / metrics_count:.1f}")

    if failed:
        print(f"\n{'=' * 80}")
        print("Failed generations:")
        print(f"{'=' * 80}")
        for name, log, err in failed:
            print(f"  - {name}")
            print(f"    Error: {err}")
            if log:
                print(f"    Log: {log}")

    if successful:
        print(f"\n{'=' * 80}")
        print("Generated apps:")
        print(f"{'=' * 80}")
        for name, app_dir, log, metrics in successful:
            print(f"  - {name}")
            print(f"    Dir: {app_dir}")
            if metrics:
                print(
                    f"    Cost: ${metrics.get('cost_usd', 0):.4f}, Tokens: {metrics.get('input_tokens', 0):,}, Turns: {metrics.get('turns', 0)}"
                )

    print(f"\n{'=' * 80}\n")

    # save results json
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backend_suffix = f"_{backend}" if backend != "claude" else ""
    output_file = out_path / f"bulk_run_results{backend_suffix}_{timestamp}.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)

    results_data = [
        {
            "app_name": name,
            "success": err is None,
            "prompt": selected_prompts.get(name),
            "app_dir": str(app_dir) if app_dir else None,
            "log_file": str(log) if log else None,
            "error": err,
            "backend": backend,
            "model": model,
            "metrics": {
                "cost_usd": metrics.get("cost_usd"),
                "input_tokens": metrics.get("input_tokens"),
                "output_tokens": metrics.get("output_tokens"),
                "turns": metrics.get("turns"),
            } if metrics else None,
        }
        for name, app_dir, log, metrics, err in results
    ]
    output_file.write_text(json.dumps(results_data, indent=2))
    print(f"Results saved to {output_file}")


if __name__ == "__main__":
    fire.Fire(main)
