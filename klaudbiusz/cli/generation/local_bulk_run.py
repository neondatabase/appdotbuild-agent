"""Local bulk app generation (no Dagger containers)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import fire
from dotenv import load_dotenv

if TYPE_CHECKING:
    from cli.generation.codegen import GenerationMetrics

load_dotenv()


def run_single(
    app_name: str,
    prompt: str,
    output_dir: Path,
) -> tuple[str, Path | None, GenerationMetrics | None, str | None]:
    """Run single app generation locally.

    Returns:
        Tuple of (app_name, app_dir, metrics, error)
    """
    from cli.generation.codegen import ClaudeAppBuilder

    try:
        builder = ClaudeAppBuilder(
            app_name=app_name,
            wipe_db=False,
            suppress_logs=False,
            output_dir=str(output_dir),
        )
        metrics = builder.run(prompt, wipe_db=False)
        app_dir = output_dir / app_name
        return (app_name, app_dir if app_dir.exists() else None, metrics, None)
    except Exception as e:
        return (app_name, None, None, str(e))


def main(
    prompts: str = "databricks",
    output_dir: str | None = None,
) -> None:
    """Local bulk app generation using skills (no MCP).

    Args:
        prompts: Prompt set to use ("databricks", "databricks_v2", or "test")
        output_dir: Custom output directory for generated apps
    """
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

    print(f"Starting LOCAL bulk generation for {len(selected_prompts)} prompts...")
    print(f"Prompt set: {prompts}")
    out_path = Path(output_dir) if output_dir else Path("./app")
    print(f"Output dir: {out_path}\n")
    out_path.mkdir(parents=True, exist_ok=True)

    results = []
    success_count = 0
    fail_count = 0

    for i, (app_name, prompt) in enumerate(selected_prompts.items(), 1):
        print(f"\n{'=' * 80}")
        print(f"[{i}/{len(selected_prompts)}] Generating: {app_name}")
        print(f"{'=' * 80}")

        app_name_result, app_dir, metrics, error = run_single(
            app_name=app_name,
            prompt=prompt,
            output_dir=out_path,
        )

        if error:
            fail_count += 1
            print(f"FAILED: {error}")
        else:
            success_count += 1
            print(f"SUCCESS: {app_dir}")

        results.append({
            "app_name": app_name_result,
            "success": error is None,
            "prompt": prompt,
            "app_dir": str(app_dir) if app_dir else None,
            "error": error,
            "backend": "claude",
            "model": None,
            "metrics": metrics,
        })

    # summary
    print(f"\n{'=' * 80}")
    print("Bulk Generation Summary")
    print(f"{'=' * 80}")
    print(f"Total prompts: {len(selected_prompts)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {fail_count}")

    # save results json
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = out_path / f"local_bulk_results_{timestamp}.json"
    output_file.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {output_file}")


if __name__ == "__main__":
    fire.Fire(main)
