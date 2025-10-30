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


# Data context for vanilla Claude SDK mode (non-MCP)
# This provides ONLY table schemas - no implementation hints
DATA_CONTEXT = """
## Application Requirements

Build a web application deployable as a Databricks App (https://www.databricks.com/product/databricks-apps).

Requirements:
- Must be a web application with a UI (choose any stack: Streamlit, Dash, Flask+React, FastAPI+React, etc.)
- Must include `app.yaml` configuration file for Databricks Apps deployment
- Must connect to Databricks SQL using environment variables
- Must be containerized (include Dockerfile)

app.yaml format:
```yaml
command: ["python", "app.py"]  # or appropriate start command
```

## Databricks Connection

Environment variables required:
- DATABRICKS_HOST
- DATABRICKS_TOKEN

## Available Sample Tables

### samples.tpch.*
- **orders**: o_orderkey, o_custkey, o_orderstatus, o_totalprice, o_orderdate, o_orderpriority
- **customer**: c_custkey, c_name, c_address, c_nationkey, c_phone, c_acctbal, c_mktsegment
- **lineitem**: l_orderkey, l_partkey, l_suppkey, l_linenumber, l_quantity, l_extendedprice, l_discount, l_tax, l_returnflag, l_linestatus, l_shipdate, l_commitdate, l_receiptdate
- **part**: p_partkey, p_name, p_mfgr, p_brand, p_type, p_size, p_container, p_retailprice
- **supplier**: s_suppkey, s_name, s_address, s_nationkey, s_phone, s_acctbal

### samples.tpcds_sf1.*
- **store_sales**: ss_sold_date_sk, ss_sold_time_sk, ss_item_sk, ss_customer_sk, ss_store_sk, ss_quantity, ss_sales_price, ss_net_paid, ss_net_profit
- **web_sales**: ws_sold_date_sk, ws_item_sk, ws_bill_customer_sk, ws_quantity, ws_sales_price, ws_net_paid, ws_net_profit
- **catalog_sales**: cs_sold_date_sk, cs_item_sk, cs_bill_customer_sk, cs_quantity, cs_sales_price, cs_net_paid, cs_net_profit
- **store_returns**: sr_returned_date_sk, sr_item_sk, sr_customer_sk, sr_return_quantity, sr_return_amt
- **customer**: c_customer_sk, c_customer_id, c_first_name, c_last_name, c_email_address, c_birth_year, c_preferred_cust_flag
- **customer_address**: ca_address_sk, ca_street_number, ca_street_name, ca_city, ca_county, ca_state, ca_zip, ca_location_type
- **date_dim**: d_date_sk, d_date, d_month_seq, d_week_seq, d_quarter_seq, d_year, d_dow, d_moy, d_dom, d_qoy
- **item**: i_item_sk, i_item_id, i_item_desc, i_current_price, i_class, i_category, i_brand, i_manager_id
- **promotion**: p_promo_sk, p_promo_id, p_promo_name, p_start_date_sk, p_end_date_sk, p_cost, p_response_target, p_channel_dmail, p_channel_email, p_channel_tv

### samples.nyctaxi.trips
- **trips**: tpep_pickup_datetime, tpep_dropoff_datetime, passenger_count, trip_distance, fare_amount, extra, tip_amount, tolls_amount, total_amount, payment_type, pickup_location_id, dropoff_location_id

"""


class RunResult(TypedDict):
    prompt: str
    success: bool
    metrics: GenerationMetrics | None
    error: str | None
    app_dir: str | None
    screenshot_path: str | None
    browser_logs_path: str | None
    enable_mcp: bool  # Track which mode was used for this generation


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

# Table hints for vanilla SDK mode - ONLY lists relevant tables, NO implementation guidance
PROMPT_TABLE_HINTS = {
    "churn-risk-dashboard": """
Relevant tables: samples.tpcds_sf1.customer, samples.tpcds_sf1.store_sales, samples.tpcds_sf1.web_sales, samples.tpcds_sf1.catalog_sales, samples.tpcds_sf1.date_dim""",

    "revenue-by-channel": """
Relevant tables: samples.tpcds_sf1.store_sales, samples.tpcds_sf1.web_sales, samples.tpcds_sf1.catalog_sales, samples.tpcds_sf1.date_dim""",

    "customer-rfm-segments": """
Relevant tables: samples.tpch.orders, samples.tpch.customer""",

    "taxi-trip-metrics": """
Relevant tables: samples.nyctaxi.trips""",

    "slow-moving-inventory": """
Relevant tables: samples.tpcds_sf1.item, samples.tpcds_sf1.store_sales, samples.tpcds_sf1.web_sales""",

    "customer-360-view": """
Relevant tables: samples.tpcds_sf1.customer, samples.tpcds_sf1.store_sales, samples.tpcds_sf1.web_sales, samples.tpcds_sf1.catalog_sales, samples.tpcds_sf1.item""",

    "product-pair-analysis": """
Relevant tables: samples.tpch.lineitem, samples.tpch.part, samples.tpch.orders""",

    "revenue-forecast-quarterly": """
Relevant tables: samples.tpcds_sf1.store_sales, samples.tpcds_sf1.web_sales, samples.tpcds_sf1.catalog_sales, samples.tpcds_sf1.date_dim""",

    "data-quality-metrics": """
Relevant tables: samples.tpcds_sf1.store_sales, samples.tpch.orders""",

    "channel-conversion-comparison": """
Relevant tables: samples.tpcds_sf1.store_sales, samples.tpcds_sf1.web_sales, samples.tpcds_sf1.catalog_sales, samples.tpcds_sf1.customer""",

    "customer-churn-analysis": """
Relevant tables: samples.tpch.orders, samples.tpch.customer""",

    "pricing-impact-analysis": """
Relevant tables: samples.tpcds_sf1.item, samples.tpcds_sf1.store_sales""",

    "supplier-scorecard": """
Relevant tables: samples.tpch.supplier, samples.tpch.lineitem""",

    "sales-density-heatmap": """
Relevant tables: samples.tpcds_sf1.customer_address, samples.tpcds_sf1.customer, samples.tpcds_sf1.store_sales, samples.tpcds_sf1.web_sales""",

    "cac-by-channel": """
Relevant tables: samples.tpcds_sf1.promotion, samples.tpcds_sf1.store_sales, samples.tpcds_sf1.web_sales""",

    "subscription-tier-optimization": """
Relevant tables: samples.tpcds_sf1.customer, samples.tpcds_sf1.store_sales, samples.tpcds_sf1.web_sales, samples.tpcds_sf1.catalog_sales""",

    "product-profitability": """
Relevant tables: samples.tpcds_sf1.item, samples.tpcds_sf1.store_sales, samples.tpcds_sf1.store_returns""",

    "warehouse-efficiency": """
Relevant tables: samples.tpch.orders, samples.tpch.lineitem""",

    "customer-ltv-cohorts": """
Relevant tables: samples.tpch.orders, samples.tpch.customer""",

    "promotion-roi-analysis": """
Relevant tables: samples.tpcds_sf1.promotion, samples.tpcds_sf1.store_sales, samples.tpcds_sf1.web_sales, samples.tpcds_sf1.date_dim""",
}


def get_prompt_with_context(app_name: str, base_prompt: str, enable_mcp: bool = True) -> str:
    """Get the appropriate prompt based on MCP enablement.

    Args:
        app_name: Name of the app
        base_prompt: Base prompt text
        enable_mcp: If True (default), use prompt as-is (MCP provides Databricks access).
                   If False, enrich prompt with Databricks context and table schemas.

    Returns:
        Prompt string ready to use
    """
    if enable_mcp:
        # MCP mode - use prompt as-is, MCP will provide Databricks access
        return base_prompt
    else:
        # Pure SDK mode - add Databricks context and table hints to prompt
        table_hint = PROMPT_TABLE_HINTS.get(app_name, "")
        return f"{DATA_CONTEXT}\n{base_prompt}\n{table_hint}"


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
        has_logs = False
        if logs_path.exists():
            try:
                has_logs = logs_path.stat().st_size > 0
                result["browser_logs_path"] = str(logs_path)
            except Exception:
                result["browser_logs_path"] = None
        else:
            result["browser_logs_path"] = None


def run_single_generation(
    app_name: str, prompt: str, wipe_db: bool = False, use_subagents: bool = False, enable_mcp: bool = True, mcp_binary: str | None = None
) -> RunResult:
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Generation timed out after 900 seconds")

    try:
        # set 15 minute timeout for entire generation
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(900)

        # Get the appropriate prompt based on MCP enablement
        final_prompt = get_prompt_with_context(app_name, prompt, enable_mcp)

        # Log mode for this app
        mode_str = "MCP" if enable_mcp else "SDK"
        print(f"[{mode_str}] Generating {app_name}...", flush=True)

        # Configure AppBuilder based on MCP enablement
        codegen = AppBuilder(
            app_name=app_name,
            wipe_db=wipe_db,
            suppress_logs=True,
            use_subagents=use_subagents,
            use_mcp=enable_mcp,
            mcp_binary=mcp_binary,
        )
        metrics = codegen.run(final_prompt, wipe_db=wipe_db)
        app_dir = metrics.get("app_dir") if metrics else None

        signal.alarm(0)  # cancel timeout

        return {
            "prompt": prompt,  # Store original prompt for reporting
            "success": True,
            "metrics": metrics,
            "error": None,
            "app_dir": app_dir,
            "screenshot_path": None,  # filled in later by enrichment
            "browser_logs_path": None,  # filled in later by enrichment
            "enable_mcp": enable_mcp,  # Track which mode was used
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
            "enable_mcp": enable_mcp,
        }


def main(
    wipe_db: bool = False,
    n_jobs: int = -1,
    use_subagents: bool = False,
    screenshot_concurrency: int = 5,
    screenshot_wait_time: int = 120000,
    enable_mcp: bool = True,
    mcp_binary: str | None = None,
) -> None:
    """Run bulk generation of apps from prompts.

    Args:
        wipe_db: Whether to wipe the database before running
        n_jobs: Number of parallel jobs (-1 for all CPUs)
        use_subagents: Whether to use subagents in generation
        screenshot_concurrency: Number of concurrent screenshot processes
        screenshot_wait_time: Wait time for screenshots in ms
        enable_mcp: Enable MCP server for Databricks access (default: True).
                   If False, uses pure Claude SDK with embedded Databricks context in prompts.
    """
    # validate required environment variables
    if not os.environ.get("DATABRICKS_HOST") or not os.environ.get("DATABRICKS_TOKEN"):
        raise ValueError("DATABRICKS_HOST and DATABRICKS_TOKEN environment variables must be set")

    print(f"Starting bulk generation for {len(PROMPTS)} prompts...")
    print(f"MCP enabled: {enable_mcp}")
    print(f"Parallel jobs: {n_jobs}")
    print(f"Wipe DB: {wipe_db}")
    print(f"Use subagents: {use_subagents}")
    print(f"MCP binary: {mcp_binary if mcp_binary else 'cargo run (default)'}")
    print(f"Screenshot concurrency: {screenshot_concurrency}\n")

    if enable_mcp:
        print("Running with MCP - Databricks access via MCP server\n")
    else:
        print("Running in pure SDK mode - prompts will include Databricks table schemas\n")

    # generate all apps
    results: list[RunResult] = Parallel(n_jobs=n_jobs, verbose=10)(  # type: ignore[assignment]
        delayed(run_single_generation)(app_name, prompt, wipe_db, use_subagents, enable_mcp, mcp_binary)
        for app_name, prompt in PROMPTS.items()
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
    mode_str = "MCP (Databricks tools)" if enable_mcp else "Pure SDK (embedded context)"
    print(f"Mode: {mode_str}")
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
