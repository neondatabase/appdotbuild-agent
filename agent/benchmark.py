#!/usr/bin/env python3
"""
LLM model benchmarking tool for agent generation.

Runs a matrix ablation study capturing:
- Generated source code
- Telemetry data (via CUMULATIVE_TELEMETRY_LOG env var)
- Success/failure status based on Docker health check

Usage:
  uv run python benchmark.py
"""

import asyncio
import subprocess
import itertools
import json
import os
import csv
import sys
import shutil
import tempfile
import socket
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Any, Set
import fire
from tests.test_e2e import run_e2e


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# Port allocation for concurrent execution
_port_lock = threading.Lock()
_allocated_ports: Set[int] = set()


def find_free_port(start_port: int = 8080) -> int:
    """Find a free port starting from start_port."""
    with _port_lock:
        port = start_port
        while port in _allocated_ports or not _is_port_available(port):
            port += 1
        _allocated_ports.add(port)
        return port


def release_port(port: int) -> None:
    """Release a port back to the pool."""
    with _port_lock:
        _allocated_ports.discard(port)


def _is_port_available(port: int) -> bool:
    """Check if a port is available on localhost."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("localhost", port))
            return True
    except OSError:
        return False


def get_matrix_configurations() -> Tuple[
    Dict[str, str], List[str], Dict[str, str], Dict[str, str]
]:
    """Define the matrix components for ablation study."""

    prompts = {
        "plant-care-tracker": "A simple web app that lets users track the condition of their plants using fun plant moods based on custom rule-based logic. Avoid using AI, ML, or external APIs.",
        "roommate-chore-wheel": "An app that randomly assigns chores each week and tracks completion.",
        "car-maintenance-dashboard": "A dashboard to monitor car maintenance history and upcoming service dates.",
        "city-trip-advisor": "A simple web app that suggests if tomorrow's trip to a given city is a good idea, based on open-meteo API's weather forecast for that city.",
        # "currency-converter": "A currency conversion app that takes an amount, source currency and target currency as input and converts it using the Frankfurter API.",
        # "book-library-manager": "A web app for managing a book library where users can add, view, update, and remove books, each with details like title, author, genre, and reading status. Include user-friendly forms, list views, and the ability to search or filter books.",
        # "wellness-score-tracker": "An app where users input hours of sleep, stress levels, caffeine/alcohol intake—then get a daily 'wellness score' with historical trends.",
        # "event-tracker": "A basic event tracker that lets users add, view, and delete events with a title, date, and description. Use a clean, modern UI with minimal code in your preferred framework.",
        # "daily-pattern-visualizer": "A dashboard where users log sleep, work hours, social time, screen time, and emotional energy. Visualize patterns and suggest when to take breaks.",
        # "pantry-inventory-app": "An app where users can add and track pantry items, get expiry notifications, and, if possible, generate recipe suggestions using AI based on available ingredients.",
        # "home-lab-inventory": "An application to catalog and manage home lab infrastructure. Users should be able to track hardware assets (servers, switches), software (VMs, containers), and manage IP address allocations.",
        # "basic-inventory-system": "A web-based inventory management system for small businesses. Key features should include product management (tracking names, SKUs, and stock levels) and a system for recording stock-in and stock-out transactions.",
        # "pastel-blue-notes-app": "A minimalist notes application with a pastel blue color scheme. It should allow users to create, edit, and organize notes into folders or categories, with user accounts for syncing across devices.",
        # "teacher-question-bank": "A question bank system for teachers to create and manage questions by subject and topic. Must include a feature to automatically generate quizzes from the bank and export them to a printable format.",
        # "beer-counter-app": "A simple, single-page web app to count beers. It should feature increment, decrement, and reset buttons, and use local storage to save the count without needing a login.",
        # "plumbing-business-landing-page": "A professional, responsive landing page for a plumbing business designed for lead generation. It must include sections for services offered, customer testimonials, and a clear contact form.",
        # "kanji-flashcards": "A Kanji learning app using a spaced repetition system (SRS). It should feature interactive flashcards with Kanji, meanings, and readings, allowing users to track progress across different JLPT levels.",
        # "bookmark-management-app": "A bookmark management application that allows users to save, tag, and organize links into collections. The system should support user accounts for syncing and include a powerful search feature.",
        # "personal-expense-tracker": "A personal expense tracking application for logging income and expenses. Users should be able to assign transactions to categories, set budgets, and view a dashboard with spending visualizations.",
        # "gym-crm": "A CRM for a gym to manage class reservations. It should feature a class schedule calendar where members can book spots, and an admin interface for managing classes and attendance. GYM STYLE VISUALS PLEASE!",
        # "todo-list-with-mood": "A daily journal application that combines a to-do list with a mood tracker. Users can manage tasks and log their daily mood, with a view to see the relationship over time.",
        # "birthday-wish-app": "A simple, single-page static website to serve as a digital birthday card. It should feature a personalized message, a small photo gallery, and a simple celebratory animation.",
        # "pc-gaming-niche-site": "A content-focused niche website featuring reviews of budget PC gaming peripherals. The site should be organized by product categories (mice, keyboards, etc.) and include a simple CMS for publishing articles.",
        # "tennis-enthusiast-platform": "Hipster-looking social platform for tennis players to find partners. Users can create profiles with their skill level and location, and search for other players nearby to schedule matches.",
        # "engineering-job-board": "A nerd-style niche job board for engineering positions. It should allow employers to post jobs and job seekers to search and filter listings by engineering discipline and location",
        # "indonesian-inventory-app": "Buatkan aplikasi manajemen inventaris (stok barang) dalam Bahasa Indonesia. Fitur utama harus mencakup pengelolaan daftar barang (tambah, edit, hapus) serta pencatatan transaksi barang masuk dan barang keluar.",
        # "habit-tracker-app": "A simple app to help users build and maintain positive habits. Users can define custom habits, track their daily progress with a simple check-in, and visualize their streaks over time to stay motivated.",
        # "recipe-sharing-platform": "A warm community-based platform where users can post, browse, and save their favorite recipes. Each recipe includes ingredients, instructions, and categories, with a search feature to find new meals.",
        # "pomodoro-study-timer": "Brutally minimalistic Pomodoro timer to boost productivity. It features customizable work and break intervals, audio alerts, and a simple log to track completed study sessions throughout the day.",
        # "cat-conspiracy-tracker": "A humorous app for paranoid cat owners to log their pet's suspicious activities. The app uses a custom, non-scientific scoring system based on logged behaviors (like prolonged staring or 'gifts' of dead insects) to calculate a daily 'conspiracy level'."
    }

    template_ids = ["trpc_agent", "nicegui_agent"]

    coding_models = {
        "claude": "anthropic:claude-sonnet-4-20250514",
        # "qwen3-480b-35a": "openrouter:qwen/qwen3-coder",
        # "gpt-oss": "openrouter:openai/gpt-oss-120b",
    }

    universal_models = {
        "gemini": "gemini:gemini-2.5-flash-preview-05-20",
    }

    return prompts, template_ids, coding_models, universal_models


class GenerationCapture:
    """Helper class to capture generation artifacts."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.captured_temp_dir = None
        self.success = False

    async def run_with_capture(self, prompt: str, template_id: str) -> bool:
        """Run generation and capture all artifacts."""
        try:
            # Run the generation with standalone=False to ensure Docker health check
            await run_e2e(
                prompt=prompt,
                standalone=False,  # ensures Docker validation
                with_edit=False,
                template_id=template_id,
            )

            self.success = True
            log("Generation completed successfully")
            return True

        except Exception as e:
            log(f"Generation failed: {e}")
            self.success = False
            return False


async def run_single_generation(prompt: str, template_id: str, output_dir: str) -> None:
    """
    Run a single generation and save all artifacts.

    Args:
        prompt: The prompt to generate from
        template_id: Template ID (trpc_agent, nicegui_agent, laravel_agent)
        output_dir: Directory to save all artifacts
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    log("Starting generation:")
    log(f"  Prompt: {prompt[:50]}...")
    log(f"  Template: {template_id}")
    log(f"  Output: {output_dir}")

    # Initialize capture helper
    capture = GenerationCapture(output_dir)

    # We need to monkey patch run_e2e to capture the temp_dir
    # The challenge is that run_e2e creates its own tempfile.TemporaryDirectory
    # We'll patch tempfile.TemporaryDirectory to capture the path
    original_tempdir = tempfile.TemporaryDirectory
    captured_dirs = []

    class CapturingTempDir(original_tempdir):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured_dirs.append(self.name)

        def __enter__(self):
            result = super().__enter__()
            if len(captured_dirs) > 0:
                capture.captured_temp_dir = captured_dirs[-1]
            return result

        def __exit__(self, exc_type, exc_val, exc_tb):
            # Copy contents before the original __exit__ deletes the directory
            if (
                capture.captured_temp_dir
                and Path(capture.captured_temp_dir).exists()
                and capture.captured_temp_dir == self.name
            ):
                try:
                    source_dir = output_path / "source_code"
                    if source_dir.exists():
                        shutil.rmtree(source_dir)

                    # Copy the entire generated project before cleanup
                    shutil.copytree(self.name, source_dir)
                    log(f"Source code saved to {source_dir}")

                    # List what was generated for debugging
                    generated_files = list(source_dir.rglob("*"))
                    log(f"Generated {len(generated_files)} files/directories")
                except Exception as e:
                    log(f"Failed to copy temp directory: {e}")

            # Now let the original cleanup happen
            return super().__exit__(exc_type, exc_val, exc_tb)

    # Apply monkey patch
    tempfile.TemporaryDirectory = CapturingTempDir

    try:
        # Run the generation
        success = await capture.run_with_capture(prompt, template_id)

        # Copying happens automatically in CapturingTempDir.__exit__

        # Exit with appropriate code
        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"Fatal error in generation: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(2)

    finally:
        # Restore original tempfile
        tempfile.TemporaryDirectory = original_tempdir


def save_run_results(
    run_dir: Path,
    subprocess_result: subprocess.CompletedProcess,
    env_vars: Dict[str, str],
    duration: float,
    config_info: Dict[str, Any],
) -> None:
    """Save all run artifacts and results."""

    # Determine success based on exit code (run_e2e raises exception if Docker unhealthy)
    success = subprocess_result.returncode == 0
    docker_healthy = success  # If exit code is 0, Docker was healthy

    status = {
        "success": success,
        "exit_code": subprocess_result.returncode,
        "docker_healthy": docker_healthy,
        "duration_seconds": duration,
        "timestamp": datetime.now().isoformat(),
        "config": {
            "prompt_name": config_info["prompt_name"],
            "template_id": config_info["template_id"],
            "coding_model_name": config_info["coding_model_name"],
            "universal_model_name": config_info["universal_model_name"],
            "LLM_BEST_CODING_MODEL": env_vars.get("LLM_BEST_CODING_MODEL"),
            "LLM_UNIVERSAL_MODEL": env_vars.get("LLM_UNIVERSAL_MODEL"),
            "CUMULATIVE_TELEMETRY_LOG": env_vars.get("CUMULATIVE_TELEMETRY_LOG"),
        },
    }

    # Save all artifacts
    (run_dir / "status.json").write_text(json.dumps(status, indent=2))
    (run_dir / "stdout.log").write_text(subprocess_result.stdout)
    (run_dir / "stderr.log").write_text(subprocess_result.stderr)

    log(f"  Result: {'✓ SUCCESS' if success else '✗ FAILED'}")
    if not success:
        log(
            f"  Error: Exit code {subprocess_result.returncode}, Docker healthy: {docker_healthy}"
        )


def generate_summary(results_dir: Path = Path("benchmark_results")) -> None:
    """Generate CSV summary of all runs."""
    results = []

    for run_dir in results_dir.iterdir():
        if not run_dir.is_dir():
            continue

        status_file = run_dir / "status.json"
        if not status_file.exists():
            continue

        # Load status
        status = json.loads(status_file.read_text())

        # Load telemetry if exists
        telemetry_file = run_dir / "telemetry.json"
        total_tokens = 0
        total_calls = 0
        if telemetry_file.exists():
            telemetry = json.loads(telemetry_file.read_text())
            for model_stats in telemetry.values():
                total_tokens += model_stats.get(
                    "total_input_tokens", 0
                ) + model_stats.get("total_output_tokens", 0)
                total_calls += model_stats.get("total_calls", 0)

        config = status.get("config", {})
        results.append(
            {
                "run_name": run_dir.name,
                "prompt_name": config.get("prompt_name"),
                "template_id": config.get("template_id"),
                "coding_model": config.get("coding_model_name"),
                "universal_model": config.get("universal_model_name"),
                "success": status["success"],
                "docker_healthy": status["docker_healthy"],
                "duration_seconds": status["duration_seconds"],
                "total_tokens": total_tokens,
                "total_model_calls": total_calls,
                "exit_code": status["exit_code"],
                "timestamp": status["timestamp"],
            }
        )

    if not results:
        print("No results found to summarize")
        return

    # Save as CSV
    summary_file = results_dir / "summary.csv"
    with open(summary_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    log(f"Summary saved to {summary_file}")

    # Print quick stats
    total_runs = len(results)
    successful_runs = sum(1 for r in results if r["success"])
    log(f"Total runs: {total_runs}")
    log(f"Successful runs: {successful_runs}")
    log(f"Success rate: {successful_runs / total_runs * 100:.1f}%")


def single(prompt: str, template_id: str, output_dir: str) -> None:
    """Run a single generation."""
    asyncio.run(run_single_generation(prompt, template_id, output_dir))


def run_single_benchmark(
    config: Tuple,
    idx: int,
    total: int,
    results_dir: Path,
    timeout_minutes: int,
    resume: bool,
) -> None:
    """Run a single benchmark configuration."""
    (
        (prompt_name, prompt_text),
        template_id,
        (coding_name, coding_model),
        (universal_name, universal_model),
    ) = config

    # Generate readable run name
    run_name = (
        f"{prompt_name}_{template_id.replace('_', '-')}_{coding_name}_{universal_name}"
    )
    run_dir = results_dir / run_name

    # Skip if already completed and in resume mode
    if resume and (run_dir / "status.json").exists():
        log(f"[{idx}/{total}] Skipping {run_name} - already completed")
        return

    # Allocate unique ports for this run
    host_port = find_free_port()
    trpc_port = find_free_port(
        host_port + 1000
    )  # tRPC backend port offset to avoid conflicts
    agent_server_port = find_free_port(
        host_port + 2000
    )  # agent server port offset to avoid conflicts

    try:
        log(
            f"[{idx}/{total}] Running: {run_name} (ports: {host_port}, {trpc_port}, agent: {agent_server_port})"
        )
        run_dir.mkdir(parents=True, exist_ok=True)

        # Set unique telemetry log path
        telemetry_path = run_dir / "telemetry.json"

        # Prepare environment
        env = os.environ.copy()
        env["CUMULATIVE_TELEMETRY_LOG"] = str(telemetry_path)
        env["LLM_BEST_CODING_MODEL"] = coding_model
        env["LLM_UNIVERSAL_MODEL"] = universal_model
        env["HOST_PORT"] = str(host_port)
        env["HOST_PORT_TRPC"] = str(trpc_port)
        env["AGENT_SERVER_PORT"] = str(agent_server_port)

        config_info = {
            "prompt_name": prompt_name,
            "template_id": template_id,
            "coding_model_name": coding_name,
            "universal_model_name": universal_name,
        }

        # Run generation subprocess
        start_time = datetime.now()
        process = None
        try:
            process = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "python",
                    "benchmark.py",
                    "single",
                    "--prompt",
                    prompt_text,
                    "--template-id",
                    template_id,
                    "--output-dir",
                    str(run_dir),
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # wait for completion with timeout
            stdout, stderr = process.communicate(timeout=timeout_minutes * 60)
            result = subprocess.CompletedProcess(
                args=process.args,
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
            )

        except subprocess.TimeoutExpired:
            log(f"  [{idx}/{total}] TIMEOUT {run_name} after {timeout_minutes} minutes")

            # first try graceful termination to allow telemetry saving
            if process:
                try:
                    process.terminate()  # sends SIGTERM
                    stdout, stderr = process.communicate(
                        timeout=5
                    )  # give 5 seconds for graceful shutdown
                    log("  Process terminated gracefully")
                except subprocess.TimeoutExpired:
                    # if graceful termination fails, force kill
                    log("  Graceful termination failed, force killing process")
                    process.kill()
                    stdout, stderr = process.communicate()

                result = subprocess.CompletedProcess(
                    args=process.args,
                    returncode=124,
                    stdout=stdout or "",
                    stderr=(stderr or "")
                    + f"\nProcess timed out after {timeout_minutes} minutes",
                )
            else:
                # fallback for the unlikely case where process wasn't created
                result = subprocess.CompletedProcess(
                    args=[],
                    returncode=124,
                    stdout="",
                    stderr=f"Process timed out after {timeout_minutes} minutes",
                )

        duration = (datetime.now() - start_time).total_seconds()

        # Save results
        save_run_results(run_dir, result, env, duration, config_info)

    finally:
        # Always release the allocated ports
        release_port(host_port)
        release_port(trpc_port)
        release_port(agent_server_port)


def matrix(concurrent: int = 1, resume=True) -> None:
    """Run the full matrix benchmark study.

    Args:
        concurrent: Number of parallel runs (1 = sequential, >1 = concurrent)
    """
    summary_only = False
    filter_template = None
    filter_prompt = None
    timeout_minutes = 25

    if summary_only:
        generate_summary()
        return

    prompts, template_ids, coding_models, universal_models = get_matrix_configurations()

    # Apply filters if specified
    if filter_template:
        template_ids = [t for t in template_ids if t == filter_template]
    if filter_prompt:
        prompts = {k: v for k, v in prompts.items() if k == filter_prompt}

    # Generate all combinations
    matrix_combinations = list(
        itertools.product(
            prompts.items(),
            template_ids,
            coding_models.items(),
            universal_models.items(),
        )
    )

    log(f"Total runs to execute: {len(matrix_combinations)}")
    log(f"Concurrency level: {concurrent}")
    if resume:
        log("Resume mode: will skip completed runs")

    results_dir = Path("benchmark_results")
    results_dir.mkdir(exist_ok=True)

    if concurrent <= 1:
        # Sequential execution (backward compatible)
        for idx, config in enumerate(matrix_combinations, 1):
            run_single_benchmark(
                config,
                idx,
                len(matrix_combinations),
                results_dir,
                timeout_minutes,
                resume,
            )
    else:
        # Concurrent execution using ThreadPoolExecutor
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Limit concurrency to avoid resource exhaustion
        max_concurrent = min(concurrent, 8)  # Hard limit of 8 parallel runs
        log(f"Using {max_concurrent} concurrent workers")

        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            # Submit all tasks
            futures = []
            for idx, config in enumerate(matrix_combinations, 1):
                future = executor.submit(
                    run_single_benchmark,
                    config,
                    idx,
                    len(matrix_combinations),
                    results_dir,
                    timeout_minutes,
                    resume,
                )
                futures.append(future)

            # Wait for completion and handle any exceptions
            completed = 0
            for future in as_completed(futures):
                try:
                    future.result()  # This will raise any exception that occurred
                    completed += 1
                except Exception as e:
                    log(f"Error in concurrent execution: {e}")
                    completed += 1

    log("=" * 50)
    log("Matrix benchmark completed!")
    log("Generating summary...")
    generate_summary(results_dir)


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1:
        # Default to matrix if no args
        matrix()
    else:
        fire.Fire({"single": single, "matrix": matrix})
