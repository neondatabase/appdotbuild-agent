import os
import sys
import pytest
import subprocess
import tomllib
from pathlib import Path
from datetime import datetime

import anyio
from fire import Fire
import coloredlogs


def _current_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _n_workers():
    return str(min(os.cpu_count() or 1, 4))


def _run_tests_with_cache(dest=".", n_workers=_n_workers(), verbose=False, exclude: str | None = None):
    os.environ["LLM_VCR_CACHE_MODE"] = "lru"
    os.chdir(_current_dir())
    flag = "-vs" if verbose else "-v"
    params = [flag, "-n", str(n_workers), dest]
    if exclude:
        params += ["-k", f"not {exclude}"]
    code = pytest.main(params)
    sys.exit(code)


def run_tests_with_cache():
    Fire(_run_tests_with_cache)


def update_cache(dest="."):
    os.environ["LLM_VCR_CACHE_MODE"] = "record"
    os.chdir(_current_dir())
    code = pytest.main(["-v", "-n", "0", dest])
    if code != 0:
        raise RuntimeError(f"pytest failed with code {code}")


def run_lint():
    os.chdir(_current_dir())
    code = subprocess.run("uv run ruff check . --fix".split())
    sys.exit(code.returncode)


def _run_format(dest="."):
    os.chdir(_current_dir())
    code = subprocess.run(f"uv run ruff format {dest}".split())
    sys.exit(code.returncode)


def run_format():
    Fire(_run_format)


def run_e2e_tests():
    Fire(_run_e2e_tests)


def _run_e2e_tests(template=None):
    coloredlogs.install(level="INFO")
    os.chdir(_current_dir())

    args = ["-v", "-n", "0", "tests/test_e2e.py"]

    if template:
        # Run only tests marked with the specific template
        args.extend(["-m", template])

    code = pytest.main(args)
    sys.exit(code)


def generate():
    os.environ["LLM_VCR_CACHE_MODE"] = os.environ.get("LLM_VCR_CACHE_MODE", "lru")
    return Fire(_generate)


def _run_edit_mode(prompt, input_folder, template_id, use_databricks):
    """Run the agent in edit mode on an existing project folder"""
    from api.agent_server.agent_api_client import spawn_local_server, get_all_files_from_project_dir, apply_patch, latest_unified_diff
    from api.agent_server.agent_client import AgentApiClient, MessageKind
    from log import get_logger
    
    logger = get_logger(__name__)
    
    async def run_edit():
        # Read all files from the input folder
        input_folder_abs = os.path.abspath(input_folder)
        logger.info(f"Running in edit mode on folder: {input_folder_abs}")
        logger.info(f"Using prompt: {prompt}")
        
        files_for_snapshot = get_all_files_from_project_dir(input_folder_abs)
        all_files = [f.model_dump() for f in files_for_snapshot]
        
        if not all_files:
            logger.warning(f"No files found in {input_folder_abs}")
            print(f"Warning: No files found in {input_folder_abs}")
        
        settings = {}
        if use_databricks:
            settings = {
                "databricks_host": os.getenv("DATABRICKS_HOST"),
                "databricks_token": os.getenv("DATABRICKS_TOKEN"),
            }
            if not settings["databricks_host"] or not settings["databricks_token"]:
                raise ValueError("Databricks host and token must be set in environment variables to use Databricks")
        
        with spawn_local_server():
            async with AgentApiClient() as client:
                # Send the prompt with all existing files as context
                logger.info(f"Sending edit request with {len(all_files)} files as context")
                events, request = await client.send_message(
                    prompt, 
                    template_id=template_id, 
                    settings=settings,
                    all_files=all_files
                )
                
                assert events, "No response received from agent"
                
                # Handle refinement requests
                max_refinements = 5
                refinement_count = 0
                
                while (events[-1].message.kind == MessageKind.REFINEMENT_REQUEST and
                       refinement_count < max_refinements):
                    events, request = await client.continue_conversation(
                        previous_events=events,
                        previous_request=request,
                        message="just do it! no more questions, please",
                        template_id=template_id,
                        settings=settings,
                        all_files=all_files
                    )
                    refinement_count += 1
                    logger.info(f"Refinement attempt {refinement_count}/{max_refinements}")
                
                if refinement_count >= max_refinements:
                    logger.error("Maximum refinement attempts exceeded")
                    raise RuntimeError("Agent stuck in refinement loop - exceeded maximum attempts")
                
                # Get the diff
                diff = latest_unified_diff(events)
                if not diff:
                    logger.warning("No diff was generated in the agent response")
                    print("No changes were generated by the agent")
                    return
                
                # Apply the diff to the input folder
                logger.info("Applying generated changes to the input folder")
                
                # Create a backup of the original folder
                backup_dir = f"{input_folder_abs}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                import shutil
                shutil.copytree(input_folder_abs, backup_dir)
                logger.info(f"Created backup at: {backup_dir}")
                print(f"Backup created at: {backup_dir}")
                
                # Apply the patch to the original folder (no template needed for edit mode)
                success, message = apply_patch(diff, input_folder_abs, "")
                if success:
                    print(f"✅ Successfully applied changes to {input_folder_abs}")
                    logger.info(f"Successfully applied patch to {input_folder_abs}")
                else:
                    print(f"❌ Failed to apply changes: {message}")
                    logger.error(f"Failed to apply patch: {message}")
                    print(f"Original folder preserved. Backup available at: {backup_dir}")
                    sys.exit(1)
    
    anyio.run(run_edit)


def _generate(prompt=None, template_id=None, with_edit=True, use_databricks=False, edit_mode=False, input_folder=None, monitor=False):
    from tests.test_e2e import DEFAULT_APP_REQUEST
    coloredlogs.install(level="INFO")
    
    if prompt is None:
        prompt = DEFAULT_APP_REQUEST
    
    if edit_mode:
        if not input_folder:
            print("Error: --input-folder is required when using --edit-mode")
            sys.exit(1)
        if not os.path.exists(input_folder):
            print(f"Error: Input folder '{input_folder}' does not exist")
            sys.exit(1)
        _run_edit_mode(prompt, input_folder, template_id, use_databricks)
    elif monitor:
        # Monitor mode can work with existing project or generate new one
        if input_folder:
            # Monitor existing project with auto-fix capability
            if not os.path.exists(input_folder):
                print(f"Error: Input folder '{input_folder}' does not exist")
                sys.exit(1)
            from tests.test_e2e import run_monitor_existing_project
            anyio.run(run_monitor_existing_project, input_folder, prompt, template_id, use_databricks)
        else:
            # Generate new project and monitor it
            from tests.test_e2e import run_e2e_with_monitoring
            anyio.run(run_e2e_with_monitoring, prompt, True, with_edit, template_id, use_databricks)
    else:
        from tests.test_e2e import run_e2e
        anyio.run(run_e2e, prompt, True, with_edit, template_id, use_databricks)


def interactive():
    """Run the agent in interactive mode"""
    coloredlogs.install(level="INFO")
    os.environ["LLM_VCR_CACHE_MODE"] = os.environ.get("LLM_VCR_CACHE_MODE", "lru")
    return Fire(_interactive)


def _interactive(edit_mode=False, input_folder=None, **kwargs):
    """Interactive mode with optional edit mode support
    
    Args:
        edit_mode: Enable edit mode for existing projects
        input_folder: Path to existing project folder (required with edit_mode)
        **kwargs: Additional arguments passed to CLI
    """
    from api.agent_server.agent_api_client import cli as _run_interactive
    
    if edit_mode:
        if not input_folder:
            print("Error: --input-folder is required when using --edit-mode")
            sys.exit(1)
        if not os.path.exists(input_folder):
            print(f"Error: Input folder '{input_folder}' does not exist")
            sys.exit(1)
        
        # Set environment variable to indicate edit mode
        os.environ["AGENT_EDIT_MODE"] = "true"
        os.environ["AGENT_PROJECT_DIR"] = os.path.abspath(input_folder)
        print(f"Starting interactive mode in EDIT mode for: {input_folder}")
    
    _run_interactive(**kwargs)


def type_check():
    code = subprocess.run("uv run pyright .".split())
    sys.exit(code.returncode)


def help_command():
    """Displays all available custom uv run commands with examples."""
    if tomllib is None:
        print("Cannot display help: tomllib module is not available. Please use Python 3.11+ or install 'toml'.")
        return

    print("Available custom commands (run with 'uv run <command>'):\n")

    # Fallback examples, primarily for commands not documented in pyproject.toml
    fallback_examples = {
        "generate": "uv run generate --prompt='your app description' (Generates code based on a prompt)",
        "interactive": "uv run interactive (Starts an interactive CLI session with the agent)",
    }

    # Define pyproject_path at the top level so it's accessible in the exception handlers
    current_script_path = Path(__file__).resolve()
    pyproject_path = current_script_path.parent / "pyproject.toml"

    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)

        scripts = data.get("project", {}).get("scripts", {})
        command_docs = data.get("tool", {}).get("agent", {}).get("command_docs", {})

        if not scripts:
            print("No custom scripts found in pyproject.toml.")
            # Ensure help command itself can be shown if pyproject.toml is minimal/empty
            # and has a doc string in command_docs or fallback_examples
            scripts = {"help": "commands:help_command"}
            if "help" not in command_docs and "help" not in fallback_examples:
                # Provide a very basic default if no doc is available anywhere
                command_docs["help"] = "Displays this help message. Example: uv run help"

        # Ensure help is in the list for display, especially if pyproject.toml is empty or lacks it.
        if "help" not in scripts:
            scripts["help"] = "commands:help_command"

        all_command_names = set(scripts.keys())
        if not all_command_names:
            max_len = len("Command") + 2
        else:
            max_len = max(len(name) for name in all_command_names) + 2

        print(f"{'Command':<{max_len}} {'Description / Example'}")
        print(f"{'=' * max_len} {'=' * 40}")  # Using '=' for a slightly different look

        for name, target in sorted(scripts.items()):
            # Prioritize help string from [tool.agent.command_docs]
            help_text = command_docs.get(name)
            if not help_text:
                # Fallback to the python dictionary
                help_text = fallback_examples.get(name)
            if not help_text:
                # Generic fallback if no specific help string is found
                help_text = f"uv run {name} (Target: {target})"

            print(f"{name:<{max_len}} {help_text}")

        print(
            "\nNote: Some commands might accept additional arguments. Refer to their implementations or detailed docs."
        )

    except FileNotFoundError:
        print(f"Error: pyproject.toml not found at expected location: {pyproject_path}")
    except Exception as e:
        print(f"An error occurred while reading pyproject.toml: {e}")
