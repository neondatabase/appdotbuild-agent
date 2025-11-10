"""Bulk runner for generating multiple apps from hardcoded prompts."""

import json
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv
from joblib import Parallel, delayed

from codegen import ClaudeAppBuilder
from codegen import GenerationMetrics as ClaudeGenerationMetrics
from codegen_multi import LiteLLMAppBuilder
from prompts_databricks import PROMPTS as DATABRICKS_PROMPTS
from screenshot import screenshot_apps

# Disable LiteLLM's async logging to avoid event loop issues with joblib
import litellm
litellm.turn_off_message_logging = True
litellm.drop_params = True  # silently drop unsupported params instead of warning

# Unified type for metrics from both backends
GenerationMetrics = ClaudeGenerationMetrics

# Load environment variables from .env file
load_dotenv()

# Re-export for eval compatibility
PROMPTS = DATABRICKS_PROMPTS


class RunResult(TypedDict):
    prompt: str
    success: bool
    metrics: GenerationMetrics | None
    error: str | None
    app_dir: str | None
    screenshot_path: str | None
    browser_logs_path: str | None


def enrich_results_with_screenshots(results: list[RunResult]) -> None:
    """Enrich results by checking filesystem for screenshots and logs.

    Modifies results in-place, adding screenshot_path and has_logs flags.
    """
    for result in results:
        app_dir = result.get("app_dir")
        if not app_dir:
            continue

        screenshot_path = Path(app_dir) / "screenshot_output" / "screenshot.png"
        logs_path = Path(app_dir) / "screenshot_output" / "logs.txt"

        result["screenshot_path"] = str(screenshot_path) if screenshot_path.exists() else None

        # check if logs exist and are non-empty
        if logs_path.exists():
            try:
                if logs_path.stat().st_size > 0:
                    result["browser_logs_path"] = str(logs_path)
                else:
                    result["browser_logs_path"] = None
            except Exception:
                result["browser_logs_path"] = None
        else:
            result["browser_logs_path"] = None


def run_single_generation(
    app_name: str,
    prompt: str,
    backend: str,
    model: str | None,
    wipe_db: bool = False,
    use_subagents: bool = False,
    suppress_logs: bool = True,
    mcp_binary: str | None = None,
) -> RunResult:
    # Ensure LiteLLM is configured fresh in each worker process
    if backend == "litellm":
        import litellm
        litellm.turn_off_message_logging = True
        litellm.drop_params = True

    def timeout_handler(signum, frame):
        raise TimeoutError("Generation timed out after 1200 seconds")

    try:
        # set 20 minute timeout for entire generation
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(1200)

        match backend:
            case "claude":
                codegen = ClaudeAppBuilder(
                    app_name=app_name, wipe_db=wipe_db, suppress_logs=suppress_logs, use_subagents=use_subagents, mcp_binary=mcp_binary
                )
                metrics = codegen.run(prompt, wipe_db=wipe_db)
                app_dir = metrics.get("app_dir") if metrics else None
            case "litellm":
                if not model:
                    raise ValueError("--model is required when using --backend=litellm")
                builder = LiteLLMAppBuilder(
                    app_name=app_name, model=model, mcp_binary=mcp_binary, suppress_logs=suppress_logs
                )
                litellm_metrics = builder.run(prompt)
                # convert LiteLLM metrics to dict format matching Claude SDK
                metrics: GenerationMetrics = {
                    "cost_usd": litellm_metrics.cost_usd,
                    "input_tokens": litellm_metrics.input_tokens,
                    "output_tokens": litellm_metrics.output_tokens,
                    "turns": litellm_metrics.turns,
                    "app_dir": litellm_metrics.app_dir,
                }
                app_dir = litellm_metrics.app_dir
            case _:
                raise ValueError(f"Unknown backend: {backend}. Use 'claude' or 'litellm'")

        signal.alarm(0)  # cancel timeout

        return {
            "prompt": prompt,
            "success": True,
            "metrics": metrics,
            "error": None,
            "app_dir": app_dir,
            "screenshot_path": None,  # filled in later by enrichment
            "browser_logs_path": None,  # filled in later by enrichment
        }
    except TimeoutError as e:
        signal.alarm(0)  # cancel timeout
        print(f"[TIMEOUT] {prompt[:80]}...", file=sys.stderr, flush=True)
        return {
            "prompt": prompt,
            "success": False,
            "metrics": None,
            "error": str(e),
            "app_dir": None,
            "screenshot_path": None,
            "browser_logs_path": None,
        }
    except Exception as e:
        signal.alarm(0)  # cancel timeout
        print(f"[ERROR] {prompt[:80]}... - {e}", file=sys.stderr, flush=True)
        return {
            "prompt": prompt,
            "success": False,
            "metrics": None,
            "error": str(e),
            "app_dir": None,
            "screenshot_path": None,
            "browser_logs_path": None,
        }


def main(
    prompts: str = "databricks",
    backend: str = "claude",
    model: str | None = None,
    wipe_db: bool = False,
    n_jobs: int = -1,
    use_subagents: bool = False,
    screenshot_concurrency: int = 5,
    screenshot_wait_time: int = 120000,
    mcp_binary: str | None = None,
) -> None:
    """Bulk app generation from predefined prompt sets.

    Args:
        prompts: Prompt set to use ("databricks" or "test", default: "databricks")
        backend: Backend to use ("claude" or "litellm", default: "claude")
        model: LLM model (required if backend=litellm, e.g., "openrouter/minimax/minimax-m2")
        wipe_db: Whether to wipe database on start
        n_jobs: Number of parallel jobs (-1 for all cores)
        use_subagents: Whether to enable subagent delegation (claude backend only)
        screenshot_concurrency: Number of parallel screenshot captures
        screenshot_wait_time: Wait time for screenshot capture (ms)
        mcp_binary: Optional path to pre-built edda-mcp binary (default: use cargo run)

    Usage:
        # Claude backend (default) with databricks prompts (default)
        python bulk_run.py

        # Claude backend with test prompts
        python bulk_run.py --prompts=test

        # LiteLLM backend
        python bulk_run.py --backend=litellm --model=openrouter/minimax/minimax-m2
        python bulk_run.py --prompts=test --backend=litellm --model=gemini/gemini-2.5-pro
    """
    # bulk run always suppresses logs
    suppress_logs = True

    # load prompt set
    match prompts:
        case "databricks":
            from prompts_databricks import PROMPTS as selected_prompts
        case "test":
            from prompts_test import PROMPTS as selected_prompts
        case _:
            raise ValueError(f"Unknown prompt set: {prompts}. Use 'databricks' or 'test'")

    # validate backend-specific requirements
    if backend == "litellm" and not model:
        raise ValueError("--model is required when using --backend=litellm")

    # validate required environment variables
    if not os.environ.get("DATABRICKS_HOST") or not os.environ.get("DATABRICKS_TOKEN"):
        raise ValueError("DATABRICKS_HOST and DATABRICKS_TOKEN environment variables must be set")

    print(f"Starting bulk generation for {len(selected_prompts)} prompts...")
    print(f"Backend: {backend}")
    if backend == "litellm":
        print(f"Model: {model}")
    print(f"Prompt set: {prompts}")
    print(f"Parallel jobs: {n_jobs}")
    if backend == "claude":
        print(f"Wipe DB: {wipe_db}")
        print(f"Use subagents: {use_subagents}")
    print(f"MCP binary: {mcp_binary if mcp_binary else 'cargo run (default)'}")
    print(f"Screenshot concurrency: {screenshot_concurrency}\n")

    # generate all apps
    # Use multiprocessing for better isolation (MCP sessions are created in each worker process)
    backend_type = "multiprocessing"

    results: list[RunResult] = Parallel(n_jobs=n_jobs, backend=backend_type, verbose=10)(  # type: ignore[assignment]
        delayed(run_single_generation)(app_name, prompt, backend, model, wipe_db, use_subagents, suppress_logs, mcp_binary)
        for app_name, prompt in selected_prompts.items()
    )

    # separate successful and failed generations
    successful: list[RunResult] = []
    failed: list[RunResult] = []
    for r in results:
        success = r["success"]
        if success:
            successful.append(r)
        else:
            failed.append(r)

    apps_dir = "./app/"
    # batch screenshot all successful apps
    if successful:
        # get apps directory from first successful app
        first_app_dir = next((r["app_dir"] for r in successful if r["app_dir"]), None)
        if first_app_dir:
            apps_dir = str(Path(first_app_dir).parent)
            print(f"\n{'=' * 80}")
            print(f"Batch screenshotting {len(successful)} apps...")
            print(f"{'=' * 80}\n")

            try:
                screenshot_apps(
                    apps_dir, concurrency=screenshot_concurrency, wait_time=screenshot_wait_time, capture_logs=True
                )
            except Exception as e:
                print(f"Screenshot batch failed: {e}")

            # enrich results with screenshot info from filesystem
            enrich_results_with_screenshots(results)

    successful_with_metrics: list[RunResult] = []
    for r in successful:
        metrics = r["metrics"]
        if metrics is not None:
            successful_with_metrics.append(r)

    total_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    total_turns = 0
    for r in successful_with_metrics:
        metrics = r["metrics"]
        assert metrics is not None
        total_cost += metrics["cost_usd"]
        total_input_tokens += metrics["input_tokens"]
        total_output_tokens += metrics["output_tokens"]
        total_turns += metrics["turns"]
    # calculate screenshot statistics
    screenshot_successful = 0
    screenshot_failed = 0
    for r in successful:
        if r["screenshot_path"] is not None:
            screenshot_successful += 1
        else:
            # count as failed if app was generated (has app_dir) but screenshot missing
            screenshot_failed += 1

    print(f"\n{'=' * 80}")
    print("Bulk Generation Summary")
    print(f"{'=' * 80}")
    print(f"Total prompts: {len(selected_prompts)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    print(f"\nScreenshots captured: {screenshot_successful}")
    print(f"Screenshot failures: {screenshot_failed}")
    if screenshot_failed > 0:
        print("  (Screenshot logs available in JSON output)")
    print(f"\nTotal cost: ${total_cost:.4f}")
    print(f"Total input tokens: {total_input_tokens}")
    print(f"Total output tokens: {total_output_tokens}")
    print(f"Total turns: {total_turns}")

    if successful_with_metrics:
        avg_cost = total_cost / len(successful_with_metrics)
        avg_input = total_input_tokens / len(successful_with_metrics)
        avg_output = total_output_tokens / len(successful_with_metrics)
        avg_turns = total_turns / len(successful_with_metrics)
        print("\nAverage per generation:")
        print(f"  Cost: ${avg_cost:.4f}")
        print(f"  Input tokens: {avg_input:.0f}")
        print(f"  Output tokens: {avg_output:.0f}")
        print(f"  Turns: {avg_turns:.1f}")

    if len(failed) > 0:
        print(f"\n{'=' * 80}")
        print("Failed generations:")
        print(f"{'=' * 80}")
        for r in failed:
            prompt = r["prompt"]
            error = r["error"]
            print(f"  - {prompt[:50]}...")
            if error is not None:
                print(f"    Error: {error}")

    if len(successful) > 0:
        apps_with_dirs: list[tuple[str, str]] = []
        for r in successful:
            prompt = r["prompt"]
            app_dir = r["app_dir"]
            if app_dir is not None:
                apps_with_dirs.append((prompt, app_dir))

        if apps_with_dirs:
            print(f"\n{'=' * 80}")
            print("Generated apps:")
            print(f"{'=' * 80}")
            for prompt, app_dir in apps_with_dirs:
                print(f"  - {prompt[:60]}...")
                print(f"    Dir: {app_dir}")

    print(f"\n{'=' * 80}\n")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backend_suffix = f"_{backend}" if backend != "claude" else ""
    output_file = Path(apps_dir) / Path(f"bulk_run_results{backend_suffix}_{timestamp}.json")

    # ensure directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(results, indent=2))
    print(f"Results saved to {output_file}")


if __name__ == "__main__":
    import fire

    fire.Fire(main)
