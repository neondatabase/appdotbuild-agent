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

from codegen import AppBuilder, GenerationMetrics
from screenshot import screenshot_apps

# Load environment variables from .env file
load_dotenv()


class RunResult(TypedDict):
    prompt: str
    success: bool
    metrics: GenerationMetrics | None
    error: str | None
    app_dir: str | None
    screenshot_path: str | None
    browser_logs_path: str | None


PROMPTS = {
    "churn-risk-dashboard": "Build a churn risk dashboard showing customers with less than 30 day login activity, declining usage trends, and support ticket volume. Calculate a risk score.",
    "revenue-by-channel": "Show daily revenue by channel (store/web/catalog) for the last 90 days with week-over-week growth rates and contribution percentages.",
    "customer-rfm-segments": "Create customer segments using RFM analysis (recency, frequency, monetary). Show 4-5 clusters with average spend, purchase frequency, and last order date.",
    "taxi-trip-metrics": "Calculate taxi trip metrics: average fare by distance bracket and time of day. Show daily trip volume and revenue trends.",
    "slow-moving-inventory": "Identify slow-moving inventory: products with more than 90 days in stock, low turnover ratio, and current warehouse capacity by location.",
    "customer-360-view": "Create a 360-degree customer view: lifetime orders, total spent, average order value, preferred categories, and payment methods used.",
    "product-pair-analysis": "Show top 10 product pairs frequently purchased together with co-occurrence rates. Calculate potential bundle revenue opportunity.",
    "revenue-forecast-quarterly": "Show revenue trends for next quarter based on historical growth rates. Display monthly comparisons and seasonal patterns.",
    "data-quality-metrics": "Monitor data quality metrics: track completeness, outliers, and value distribution changes for key fields over time.",
    "channel-conversion-comparison": "Compare conversion rates and average order value across store/web/catalog channels. Break down by customer segment.",
    "customer-churn-analysis": "Show customer churn analysis: identify customers who stopped purchasing in last 90 days, segment by last order value and ticket history.",
    "pricing-impact-analysis": "Analyze pricing impact: compare revenue at different price points by category. Show price recommendations based on historical data.",
    "supplier-scorecard": "Build supplier scorecard: on-time delivery percentage, defect rate, average lead time, and fill rate. Rank top 10 suppliers.",
    "sales-density-heatmap": "Map sales density by zip code with heatmap visualization. Show top 20 zips by revenue and compare to population density.",
    "cac-by-channel": "Calculate CAC by marketing channel (paid search, social, email, organic). Show CAC to LTV ratio and payback period in months.",
    "subscription-tier-optimization": "Identify subscription tier optimization opportunities: show high-usage users near tier limits and low-usage users in premium tiers.",
    "product-profitability": "Show product profitability: revenue minus returns percentage minus discount cost. Rank bottom 20 products by net margin.",
    "warehouse-efficiency": "Build warehouse efficiency dashboard: orders per hour, fulfillment SLA (percentage shipped within 24 hours), and capacity utilization by facility.",
    "customer-ltv-cohorts": "Calculate customer LTV by acquisition cohort: average revenue per customer at 12, 24, 36 months. Show retention curves.",
    "promotion-roi-analysis": "Measure promotion ROI: incremental revenue during promo vs cost, with 7-day post-promotion lift. Flag underperforming promotions.",
}


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


def run_single_generation(app_name: str, prompt: str, wipe_db: bool = False, use_subagents: bool = False) -> RunResult:
    def timeout_handler(signum, frame):
        raise TimeoutError("Generation timed out after 900 seconds")

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


def main(
    wipe_db: bool = False,
    n_jobs: int = -1,
    use_subagents: bool = False,
    screenshot_concurrency: int = 5,
    screenshot_wait_time: int = 120000,
) -> None:
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
                screenshot_apps(apps_dir, concurrency=screenshot_concurrency, wait_time=screenshot_wait_time)
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
    output_file = Path(apps_dir) / Path(f"bulk_run_results_{timestamp}.json")

    output_file.write_text(json.dumps(results, indent=2))
    print(f"Results saved to {output_file}")


if __name__ == "__main__":
    import fire

    fire.Fire(main)
