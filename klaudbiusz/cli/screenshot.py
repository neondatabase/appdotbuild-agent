"""Standalone script to re-run screenshotting for generated apps."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def screenshot_apps(
    apps_dir: str,
    concurrency: int = 10,
    wait_time: int = 90000,
) -> None:
    """Run screenshotting for all apps in a directory.

    Args:
        apps_dir: Directory containing app subdirectories
        concurrency: Number of apps to screenshot in parallel
        wait_time: Timeout in milliseconds for screenshotting
    """
    apps_path = Path(apps_dir).resolve()

    if not apps_path.exists() or not apps_path.is_dir():
        raise ValueError(f"Apps directory does not exist: {apps_dir}")

    # find all app subdirectories (directories with package.json or similar)
    app_dirs = [d for d in apps_path.iterdir() if d.is_dir() and not d.name.startswith(".")]

    if not app_dirs:
        print(f"No app directories found in {apps_dir}")
        return

    print(f"Found {len(app_dirs)} apps to screenshot")
    for d in app_dirs:
        print(f"  - {d.name}")

    # validate databricks credentials
    databricks_host = os.environ.get("DATABRICKS_HOST")
    databricks_token = os.environ.get("DATABRICKS_TOKEN")

    if not databricks_host or not databricks_token:
        raise ValueError("DATABRICKS_HOST and DATABRICKS_TOKEN environment variables must be set")

    env_vars = f"DATABRICKS_HOST={databricks_host},DATABRICKS_TOKEN={databricks_token}"

    # build dagger command
    sidecar_path = Path(__file__).parent.parent.parent / "screenshot-sidecar"

    cmd = ["dagger", "call", "screenshot-apps"]
    for app_dir in app_dirs:
        cmd.extend([f"--app-sources={app_dir}"])

    cmd.extend([
        f"--env-vars={env_vars}",
        f"--concurrency={concurrency}",
        f"--wait-time={wait_time}",
    ])

    # export to temp directory
    temp_output = Path(tempfile.mkdtemp(prefix="rescreenshot_"))
    cmd.extend(["export", f"--path={temp_output}"])

    print(f"\nRunning dagger command with concurrency={concurrency}, wait_time={wait_time}ms")
    print(f"Working directory: {sidecar_path}")
    print(f"Command: {' '.join(cmd)}\n")

    try:
        # calculate timeout
        estimated_time = (len(app_dirs) / concurrency) * (wait_time / 1000 / 60)
        timeout_minutes = estimated_time + 5
        timeout_seconds = int(timeout_minutes * 60)

        print(f"Estimated time: {estimated_time:.1f}m, timeout: {timeout_minutes:.1f}m\n")

        result = subprocess.run(
            cmd,
            cwd=str(sidecar_path),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

        if result.returncode != 0:
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            raise RuntimeError(f"Dagger command failed with exit code {result.returncode}")

        print("Screenshot capture completed successfully\n")

        # copy screenshots and logs back to app directories
        successful = 0
        failed = 0

        for i, app_dir in enumerate(app_dirs):
            app_output_dir = temp_output / f"app-{i}"
            final_output_dir = app_dir / "screenshot_output"
            final_output_dir.mkdir(exist_ok=True)

            screenshot_src = app_output_dir / "screenshot.png"
            logs_src = app_output_dir / "logs.txt"
            screenshot_dest = final_output_dir / "screenshot.png"
            logs_dest = final_output_dir / "logs.txt"

            if screenshot_src.exists():
                shutil.copy2(screenshot_src, screenshot_dest)
                successful += 1
                print(f"✓ {app_dir.name}")
            else:
                failed += 1
                print(f"✗ {app_dir.name} - screenshot not generated")

            if logs_src.exists():
                shutil.copy2(logs_src, logs_dest)

        print(f"\nResults: {successful} successful, {failed} failed")

    finally:
        # cleanup temp directory
        shutil.rmtree(temp_output, ignore_errors=True)


if __name__ == "__main__":
    import fire

    fire.Fire(screenshot_apps)
