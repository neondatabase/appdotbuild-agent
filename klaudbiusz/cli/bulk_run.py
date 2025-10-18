"""Bulk runner for generating multiple apps from hardcoded prompts."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from joblib import Parallel, delayed

from codegen import AppBuilder, GenerationMetrics


class RunResult(TypedDict):
    prompt: str
    success: bool
    metrics: GenerationMetrics | None
    error: str | None
    app_dir: str | None
    screenshot_path: str | None
    screenshot_log: str | None
    browser_logs_path: str | None


PROMPTS = {
    "churn-risk-dashboard": "Build a churn risk dashboard showing customers with less than 30 day login activity, declining usage trends, and support ticket volume. Calculate a risk score.",
    "revenue-by-channel": "Show daily revenue by channel (store/web/catalog) for the last 90 days with week-over-week growth rates and contribution percentages.",
    "customer-rfm-segments": "Create customer segments using RFM analysis (recency, frequency, monetary). Show 4-5 clusters with average spend, purchase frequency, and last order date.",
    "taxi-trip-metrics": "Calculate taxi trip metrics: average fare by distance bracket and time of day. Show daily trip volume and revenue trends.",
    "slow-moving-inventory": "Identify slow-moving inventory: products with more than 90 days in stock, low turnover ratio, and current warehouse capacity by location.",
    # "customer-360-view": "Create a 360-degree customer view: lifetime orders, total spent, average order value, preferred categories, and payment methods used.",
    # "product-pair-analysis": "Show top 10 product pairs frequently purchased together with co-occurrence rates. Calculate potential bundle revenue opportunity.",
    # "revenue-forecast-quarterly": "Show revenue trends for next quarter based on historical growth rates. Display monthly comparisons and seasonal patterns.",
    # "data-quality-metrics": "Monitor data quality metrics: track completeness, outliers, and value distribution changes for key fields over time.",
    # "channel-conversion-comparison": "Compare conversion rates and average order value across store/web/catalog channels. Break down by customer segment.",
    # "customer-churn-analysis": "Show customer churn analysis: identify customers who stopped purchasing in last 90 days, segment by last order value and ticket history.",
    # "pricing-impact-analysis": "Analyze pricing impact: compare revenue at different price points by category. Show price recommendations based on historical data.",
    # "supplier-scorecard": "Build supplier scorecard: on-time delivery percentage, defect rate, average lead time, and fill rate. Rank top 10 suppliers.",
    # "sales-density-heatmap": "Map sales density by zip code with heatmap visualization. Show top 20 zips by revenue and compare to population density.",
    # "cac-by-channel": "Calculate CAC by marketing channel (paid search, social, email, organic). Show CAC to LTV ratio and payback period in months.",
    # "subscription-tier-optimization": "Identify subscription tier optimization opportunities: show high-usage users near tier limits and low-usage users in premium tiers.",
    # "product-profitability": "Show product profitability: revenue minus returns percentage minus discount cost. Rank bottom 20 products by net margin.",
    # "warehouse-efficiency": "Build warehouse efficiency dashboard: orders per hour, fulfillment SLA (percentage shipped within 24 hours), and capacity utilization by facility.",
    # "customer-ltv-cohorts": "Calculate customer LTV by acquisition cohort: average revenue per customer at 12, 24, 36 months. Show retention curves.",
    # "promotion-roi-analysis": "Measure promotion ROI: incremental revenue during promo vs cost, with 7-day post-promotion lift. Flag underperforming promotions.",
}


def capture_screenshots_batch(
    apps: list[tuple[str, str]], concurrency: int = 5
) -> dict[str, tuple[str | None, str | None, str]]:
    """Capture screenshots for multiple apps using single Playwright instance.

    Uses the screenshot-sidecar Dagger module to build and screenshot multiple
    apps with one shared browser instance for efficiency.

    Args:
        apps: List of (app_name, app_dir) tuples
        concurrency: Number of apps to screenshot in parallel (default: 5)

    Returns:
        Dict mapping app_name to (screenshot_path, browser_logs_path, log_output):
        - screenshot_path: Path to screenshot.png if successful, None otherwise
        - browser_logs_path: Path to logs.txt if successful, None otherwise
        - log_output: Full stdout/stderr from the dagger command execution
    """
    if not apps:
        return {}

    sidecar_path = Path(__file__).parent.parent.parent / "screenshot-sidecar"

    # get Databricks credentials from environment (validated at script start)
    databricks_host = os.environ["DATABRICKS_HOST"]
    databricks_token = os.environ["DATABRICKS_TOKEN"]
    env_vars = f"DATABRICKS_HOST={databricks_host},DATABRICKS_TOKEN={databricks_token}"

    # build dagger command with multiple app sources
    cmd = ["dagger", "call", "screenshot-apps"]
    for _, app_dir in apps:
        app_path = Path(app_dir).resolve()
        cmd.extend([f"--app-sources={app_path}"])

    cmd.extend(
        [
            f"--env-vars={env_vars}",
            f"--concurrency={concurrency}",
            "--wait-time=90000",  # 90s timeout for batch
        ]
    )

    # export to temp directory in /tmp for cross-filesystem compatibility
    temp_output = Path(tempfile.mkdtemp(prefix="batch_screenshots_"))
    cmd.extend(["export", f"--path={temp_output}"])

    results: dict[str, tuple[str | None, str | None, str]] = {}

    try:
        # calculate timeout: (apps / concurrency) * wait_time + 5 min overhead for builds/setup
        estimated_screenshot_time = (len(apps) / concurrency) * (90 / 60)  # minutes
        timeout_minutes = estimated_screenshot_time + 5
        timeout_seconds = int(timeout_minutes * 60)

        print(f"Running batch screenshot for {len(apps)} apps with concurrency={concurrency}")
        print(f"Estimated time: {estimated_screenshot_time:.1f}m, timeout: {timeout_minutes:.1f}m")

        result = subprocess.run(
            cmd,
            cwd=str(sidecar_path),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

        log = f"=== STDOUT ===\n{result.stdout}\n\n=== STDERR ===\n{result.stderr}\n\n=== EXIT CODE ===\n{result.returncode}"

        if result.returncode == 0 and temp_output.exists():
            # map app-{index} directories back to app names
            for i, (app_name, app_dir) in enumerate(apps):
                app_output_dir = temp_output / f"app-{i}"
                final_output_dir = Path(app_dir) / "screenshot_output"
                final_output_dir.mkdir(exist_ok=True)

                screenshot_src = app_output_dir / "screenshot.png"
                logs_src = app_output_dir / "logs.txt"
                screenshot_dest = final_output_dir / "screenshot.png"
                logs_dest = final_output_dir / "logs.txt"

                if screenshot_src.exists():
                    shutil.copy2(screenshot_src, screenshot_dest)
                    screenshot_path = str(screenshot_dest)
                else:
                    screenshot_path = None

                if logs_src.exists():
                    shutil.copy2(logs_src, logs_dest)
                    browser_logs_path = str(logs_dest)
                else:
                    browser_logs_path = None

                results[app_name] = (screenshot_path, browser_logs_path, log)

            # cleanup temp directory
            shutil.rmtree(temp_output, ignore_errors=True)
        else:
            # all apps failed
            for app_name, _ in apps:
                results[app_name] = (None, None, log)

    except subprocess.TimeoutExpired:
        log = f"Batch screenshot capture timed out after {timeout_minutes:.1f} minutes for {len(apps)} apps"
        for app_name, _ in apps:
            results[app_name] = (None, None, log)
    except Exception as e:
        log = f"Exception during batch screenshot capture: {type(e).__name__}: {str(e)}"
        for app_name, _ in apps:
            results[app_name] = (None, None, log)

    return results


def run_single_generation(app_name: str, prompt: str, wipe_db: bool = False, use_subagents: bool = False) -> RunResult:
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Generation timed out after 900 seconds")

    try:
        # set 15 minute timeout for entire generation
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(900)

        codegen = AppBuilder(app_name=app_name, wipe_db=wipe_db, suppress_logs=True, use_subagents=use_subagents)
        metrics = codegen.run(prompt, wipe_db=wipe_db)
        app_dir = metrics.get("app_dir") if metrics else None

        signal.alarm(0)  # cancel timeout

        return {
            "prompt": prompt,
            "success": True,
            "metrics": metrics,
            "error": None,
            "app_dir": app_dir,
            "screenshot_path": None,  # filled in later by batch process
            "screenshot_log": None,  # filled in later by batch process
            "browser_logs_path": None,  # filled in later by batch process
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
            "screenshot_log": None,
            "browser_logs_path": None,
        }


def main(wipe_db: bool = False, n_jobs: int = -1, use_subagents: bool = False, screenshot_concurrency: int = 5) -> None:
    # validate required environment variables
    if not os.environ.get("DATABRICKS_HOST") or not os.environ.get("DATABRICKS_TOKEN"):
        raise ValueError("DATABRICKS_HOST and DATABRICKS_TOKEN environment variables must be set")

    print(f"Starting bulk generation for {len(PROMPTS)} prompts...")
    print(f"Parallel jobs: {n_jobs}")
    print(f"Wipe DB: {wipe_db}")
    print(f"Use subagents: {use_subagents}")
    print(f"Screenshot concurrency: {screenshot_concurrency}\n")

    # generate all apps
    results: list[RunResult] = Parallel(n_jobs=n_jobs, verbose=10)(  # type: ignore[assignment]
        delayed(run_single_generation)(app_name, prompt, wipe_db, use_subagents) for app_name, prompt in PROMPTS.items()
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

    # batch screenshot all successful apps
    apps_to_screenshot: list[tuple[str, str]] = []
    app_name_to_result: dict[str, RunResult] = {}
    for r in results:
        if r["success"] and r["app_dir"]:
            # extract app_name from PROMPTS by matching prompt
            app_name = next((name for name, prompt in PROMPTS.items() if prompt == r["prompt"]), None)
            if app_name:
                apps_to_screenshot.append((app_name, r["app_dir"]))
                app_name_to_result[app_name] = r

    if apps_to_screenshot:
        print(f"\n{'=' * 80}")
        print(f"Batch screenshotting {len(apps_to_screenshot)} apps...")
        print(f"{'=' * 80}\n")

        screenshot_results = capture_screenshots_batch(apps_to_screenshot, concurrency=screenshot_concurrency)

        # update results with screenshot info
        for app_name, (screenshot_path, browser_logs_path, screenshot_log) in screenshot_results.items():
            if app_name in app_name_to_result:
                result = app_name_to_result[app_name]
                result["screenshot_path"] = screenshot_path
                result["browser_logs_path"] = browser_logs_path
                result["screenshot_log"] = screenshot_log

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
        elif r["app_dir"] is not None:  # only count as failed if app was generated but screenshot failed
            screenshot_failed += 1

    print(f"\n{'=' * 80}")
    print("Bulk Generation Summary")
    print(f"{'=' * 80}")
    print(f"Total prompts: {len(PROMPTS)}")
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
    output_file = Path(f"bulk_run_results_{timestamp}.json")

    output_file.write_text(json.dumps(results, indent=2))
    print(f"Results saved to {output_file}")


if __name__ == "__main__":
    import fire

    fire.Fire(main)
