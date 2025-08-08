import os
import pytest
import tempfile
import anyio
import asyncio
import contextlib
import subprocess

from fire import Fire
from api.agent_server.agent_client import AgentApiClient, MessageKind
from api.agent_server.agent_api_client import apply_patch, latest_unified_diff, DEFAULT_APP_REQUEST, DEFAULT_EDIT_REQUEST, spawn_local_server, get_all_files_from_project_dir
from api.docker_utils import setup_docker_env, start_docker_compose, wait_for_healthy_containers, stop_docker_compose, get_container_logs
from log import get_logger
from tests.test_utils import requires_llm_provider, requires_llm_provider_reason

logger = get_logger(__name__)

pytestmark = pytest.mark.anyio


@contextlib.contextmanager
def empty_context():
    yield

@pytest.fixture
def anyio_backend():
    return 'asyncio'

def latest_app_name_and_commit_message(events):
    """Extract the most recent app_name and commit_message from events"""
    app_name = None
    commit_message = None

    for evt in reversed(events):
        try:
            if evt.message:
                # Update app_name if found and not yet set
                if app_name is None and evt.message.app_name is not None:
                    app_name = evt.message.app_name

                # Update commit_message if found and not yet set
                if commit_message is None and evt.message.commit_message is not None:
                    commit_message = evt.message.commit_message

                # If both are set, we can break
                if app_name is not None and commit_message is not None:
                    break
        except AttributeError:
            continue

    return app_name, commit_message

async def run_e2e(prompt: str, standalone: bool, with_edit=True, template_id=None, use_databricks=False):
    context = empty_context() if standalone else spawn_local_server()
    settings = {}
    if use_databricks:
        settings = {
            "databricks_host": os.getenv("DATABRICKS_HOST"),
            "databricks_token": os.getenv("DATABRICKS_TOKEN"),
        }
        if not settings["databricks_host"] or not settings["databricks_token"]:
            raise ValueError("Databricks host and token must be set in environment variables to use Databricks")

    with context:
        async with AgentApiClient() as client:
            events, request = await client.send_message(prompt, template_id=template_id, settings=settings)
            assert events, "No response received from agent"
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
                )
                refinement_count += 1
                logger.info(f"Refinement attempt {refinement_count}/{max_refinements}")

            if refinement_count >= max_refinements:
                logger.error("Maximum refinement attempts exceeded")
                raise RuntimeError("Agent stuck in refinement loop - exceeded maximum attempts")

            diff = latest_unified_diff(events)
            assert diff, "No diff was generated in the agent response"

            # Check that app_name and commit_message are present in the response
            app_name, commit_message = latest_app_name_and_commit_message(events)
            assert app_name is not None, "No app_name was generated in the agent response"
            assert commit_message is not None, "No commit_message was generated in the agent response"
            logger.info(f"Generated app_name: {app_name}")
            logger.info(f"Generated commit_message: {commit_message}")

            with tempfile.TemporaryDirectory() as temp_dir:
                # Determine template path based on template_id
                template_paths = {
                    "nicegui_agent": "nicegui_agent/template",
                    "trpc_agent": "trpc_agent/template",
                    "laravel_agent": "laravel_agent/template",
                    None: "trpc_agent/template"  # default
                }

                # Apply the first diff
                success, message = apply_patch(diff, temp_dir, template_paths[template_id])
                assert success, f"Failed to apply first patch: {message}"

                if with_edit:
                    # Read all files from the patched directory to provide as context
                    files_for_snapshot = get_all_files_from_project_dir(temp_dir)
                    all_files = [f.model_dump() for f in files_for_snapshot]
                    
                    new_events, new_request = await client.continue_conversation(
                        previous_events=events,
                        previous_request=request,
                        message=DEFAULT_EDIT_REQUEST,
                        all_files=all_files,
                        template_id=template_id,
                        settings=settings,
                    )
                    updated_diff = latest_unified_diff(new_events)
                    assert updated_diff, "No diff was generated in the agent response after edit"
                    assert updated_diff != diff, "Edit did not produce a new diff"
                    
                    # Apply the second diff (incremental on top of first)
                    success, message = apply_patch(updated_diff, temp_dir, template_paths[template_id])
                    assert success, f"Failed to apply second patch: {message}"

                original_dir = os.getcwd()
                container_names = setup_docker_env()

                try:
                    os.chdir(temp_dir)

                    success, error_message = start_docker_compose(temp_dir, container_names["project_name"])
                    if not success:
                        # Get logs if possible for debugging
                        try:
                            logs = get_container_logs([
                                container_names["db_container_name"],
                                container_names["app_container_name"],
                            ])
                            for container, log in logs.items():
                                logger.error(f"Container {container} logs: {log}")
                        except Exception:
                            logger.error("Failed to get container logs")

                        logger.error(f"Error starting Docker containers: {error_message}")
                        raise RuntimeError(f"Failed to start Docker containers: {error_message}")

                    container_healthy = await wait_for_healthy_containers(
                        [
                            container_names["db_container_name"],
                            container_names["app_container_name"],
                        ],
                        ["db", "app"],
                        timeout=60,
                        interval=1
                    )

                    if not container_healthy:
                        breakpoint()
                        raise RuntimeError("Containers did not become healthy within the timeout period")

                    if standalone:
                        input(f"App is running on http://localhost:80/, app dir is {temp_dir}; Press Enter to continue and tear down...")
                        print("🧹Tearing down containers... ")

                finally:
                    # Restore original directory
                    os.chdir(original_dir)

                    # Clean up Docker containers
                    stop_docker_compose(temp_dir, container_names["project_name"])

@pytest.mark.parametrize("template_id", [
    pytest.param("nicegui_agent", marks=pytest.mark.nicegui),
])
async def test_e2e_generation_nicegui(template_id):
    await run_e2e(standalone=False, prompt=DEFAULT_APP_REQUEST, template_id=template_id)

@pytest.mark.skipif(requires_llm_provider(), reason=requires_llm_provider_reason)
@pytest.mark.parametrize("template_id", [
    pytest.param("trpc_agent", marks=pytest.mark.trpc)
])
async def test_e2e_generation_trpc(template_id):
    await run_e2e(standalone=False, prompt=DEFAULT_APP_REQUEST, template_id=template_id)

@pytest.mark.skip(reason="too long to run")
@pytest.mark.skipif(requires_llm_provider(), reason=requires_llm_provider_reason)
@pytest.mark.parametrize("template_id", [
    pytest.param("laravel_agent", marks=pytest.mark.laravel)
])
async def test_e2e_generation_laravel(template_id):
    await run_e2e(standalone=False, prompt=DEFAULT_APP_REQUEST, template_id=template_id)


def create_app(prompt):
    import coloredlogs

    coloredlogs.install(level="INFO")
    anyio.run(run_e2e, prompt, True)


async def run_e2e_with_monitoring(prompt: str, standalone: bool, with_edit=True, template_id=None, use_databricks=False):
    """Run e2e with log monitoring and auto-fix capabilities"""
    context = empty_context() if standalone else spawn_local_server()
    settings = {}
    if use_databricks:
        settings = {
            "databricks_host": os.getenv("DATABRICKS_HOST"),
            "databricks_token": os.getenv("DATABRICKS_TOKEN"),
        }
        if not settings["databricks_host"] or not settings["databricks_token"]:
            raise ValueError("Databricks host and token must be set in environment variables to use Databricks")

    with context:
        async with AgentApiClient() as client:
            events, request = await client.send_message(prompt, template_id=template_id, settings=settings)
            assert events, "No response received from agent"
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
                )
                refinement_count += 1
                logger.info(f"Refinement attempt {refinement_count}/{max_refinements}")

            if refinement_count >= max_refinements:
                logger.error("Maximum refinement attempts exceeded")
                raise RuntimeError("Agent stuck in refinement loop - exceeded maximum attempts")

            diff = latest_unified_diff(events)
            assert diff, "No diff was generated in the agent response"

            # Check that app_name and commit_message are present in the response
            app_name, commit_message = latest_app_name_and_commit_message(events)
            assert app_name is not None, "No app_name was generated in the agent response"
            assert commit_message is not None, "No commit_message was generated in the agent response"
            logger.info(f"Generated app_name: {app_name}")
            logger.info(f"Generated commit_message: {commit_message}")

            with tempfile.TemporaryDirectory() as temp_dir:
                # Determine template path based on template_id
                template_paths = {
                    "nicegui_agent": "nicegui_agent/template",
                    "trpc_agent": "trpc_agent/template",
                    "laravel_agent": "laravel_agent/template",
                    None: "trpc_agent/template"  # default
                }

                # Apply the first diff
                success, message = apply_patch(diff, temp_dir, template_paths[template_id])
                assert success, f"Failed to apply first patch: {message}"

                original_dir = os.getcwd()
                container_names = setup_docker_env()

                try:
                    os.chdir(temp_dir)

                    success, error_message = start_docker_compose(temp_dir, container_names["project_name"])
                    if not success:
                        logger.error(f"Error starting Docker containers: {error_message}")
                        raise RuntimeError(f"Failed to start Docker containers: {error_message}")

                    # Start monitoring task
                    monitor_task = anyio.create_task_group()
                    async with monitor_task:
                        # Create a mutable container for events and request
                        monitor_state = {
                            "events": events,
                            "request": request
                        }
                        
                        # Start the monitoring task
                        monitor_task.start_soon(
                            monitor_and_fix_errors, 
                            client, 
                            monitor_state,
                            temp_dir, 
                            container_names, 
                            template_id, 
                            settings
                        )
                        
                        # Wait for containers to be healthy
                        container_healthy = await wait_for_healthy_containers(
                            [
                                container_names["db_container_name"],
                                container_names["app_container_name"],
                            ],
                            ["db", "app"],
                            timeout=60,
                            interval=1
                        )

                        if not container_healthy:
                            raise RuntimeError("Containers did not become healthy within the timeout period")

                        if standalone:
                            print("🔍 Monitoring mode enabled! App is running on http://localhost:80/")
                            print(f"📁 App directory: {temp_dir}")
                            print("👀 Watching logs for errors and applying fixes automatically...")
                            print("Press Ctrl+C to stop monitoring and tear down...")
                            
                            try:
                                while True:
                                    await anyio.sleep(1)
                            except KeyboardInterrupt:
                                print("\n🛑 Stopping monitoring...")
                                monitor_task.cancel_scope.cancel()

                finally:
                    # Restore original directory
                    os.chdir(original_dir)

                    # Clean up Docker containers
                    stop_docker_compose(temp_dir, container_names["project_name"])


async def monitor_and_fix_errors(client, monitor_state, temp_dir, container_names, template_id, settings):
    """Monitor container logs and apply fixes when errors are detected"""
    import re
    
    # Extract events and request from mutable state
    events = monitor_state["events"]
    request = monitor_state["request"]
    
    fixed_errors = set()
    monitoring = True
    consecutive_clean_checks = 0
    max_clean_checks = 5  # After 5 clean checks, reduce monitoring frequency
    
    logger.info("Starting error monitoring...")
    print("\n📊 Monitoring Dashboard:")
    print("="*50)
    
    while monitoring:
        try:
            # Adaptive monitoring frequency
            if consecutive_clean_checks >= max_clean_checks:
                await anyio.sleep(5)  # Check less frequently when stable
            else:
                await anyio.sleep(2)  # Check more frequently initially
            
            # Get container logs
            logs = get_container_logs([
                container_names["app_container_name"],
            ])
            
            app_logs = logs.get(container_names["app_container_name"], "")
            
            # Detect common NiceGUI and Python errors
            error_patterns = [
                # Python errors
                (r"AttributeError: '(\w+)' object has no attribute '(\w+)'", "attribute_error"),
                (r"NameError: name '(\w+)' is not defined", "name_error"),
                (r"ImportError: cannot import name '(\w+)'", "import_error"),
                (r"TypeError: (\w+)\(\) missing \d+ required positional argument", "type_error"),
                (r"ModuleNotFoundError: No module named '(\w+)'", "module_error"),
                (r"SyntaxError: (.+)", "syntax_error"),
                (r"ValueError: (.+)", "value_error"),
                (r"KeyError: '(\w+)'", "key_error"),
                # NiceGUI specific errors
                (r"nicegui\.\w+Error: (.+)", "nicegui_error"),
                (r"Failed to bind element: (.+)", "binding_error"),
                (r"Invalid NiceGUI component: (.+)", "component_error"),
                # Database errors
                (r"sqlalchemy\.exc\.\w+: (.+)", "database_error"),
                (r"psycopg2\.\w+: (.+)", "postgres_error"),
                # FastAPI/uvicorn errors
                (r"ERROR:.*uvicorn\.error: (.+)", "server_error"),
                (r"fastapi\.exceptions\.\w+: (.+)", "fastapi_error"),
            ]
            
            for pattern, error_type in error_patterns:
                matches = re.findall(pattern, app_logs)
                for match in matches:
                    error_key = f"{error_type}:{match}"
                    
                    if error_key not in fixed_errors:
                        consecutive_clean_checks = 0  # Reset clean check counter
                        logger.info(f"🔧 Detected {error_type}: {match}")
                        print(f"\n🚨 Error detected: {error_type}")
                        print(f"   Details: {match}")
                        print("   Status: Applying fix...")
                        
                        fixed_errors.add(error_key)
                        
                        # Create fix prompt based on error type
                        fix_prompt = generate_fix_prompt(error_type, match, app_logs)
                        
                        # Apply fix using agent
                        success, updated_events, updated_request = await apply_fix(
                            client, events, request, fix_prompt, temp_dir, template_id, settings, container_names
                        )
                        
                        # Update events and request for next fixes in the mutable state
                        events = updated_events
                        request = updated_request
                        monitor_state["events"] = events
                        monitor_state["request"] = request
                        
                        if success:
                            print("   Result: ✅ Fix applied and container restarted")
                        else:
                            print("   Result: ⚠️ Fix attempt completed, monitoring continues")
                        
                        # Don't need to wait here since apply_fix already waits for health
                        break  # Apply one fix at a time
            
            # If no errors found in this iteration
            error_found = False
            for pattern, _ in error_patterns:
                if re.findall(pattern, app_logs):
                    error_found = True
                    break
            
            if not error_found:
                consecutive_clean_checks += 1
                if consecutive_clean_checks == 1:
                    print("\n✅ Application running without errors")
                elif consecutive_clean_checks == max_clean_checks:
                    print("🎉 Application stable - reducing monitoring frequency")
                        
        except asyncio.CancelledError:
            monitoring = False
            logger.info("Monitoring cancelled")
            break
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            await anyio.sleep(5)


def generate_fix_prompt(error_type: str, match, full_logs: str):
    """Generate a fix prompt based on the error type"""
    context_lines = full_logs.split('\n')[-50:]  # Last 50 lines for context
    context = '\n'.join(context_lines)
    
    prompts = {
        "attribute_error": f"Fix the AttributeError where {match[0] if isinstance(match, tuple) else match} object has no attribute {match[1] if isinstance(match, tuple) else ''}. Context:\n{context}",
        "name_error": f"Fix the NameError where {match} is not defined. Context:\n{context}",
        "import_error": f"Fix the ImportError for {match}. Context:\n{context}",
        "type_error": f"Fix the TypeError: {match}. Context:\n{context}",
        "module_error": f"Fix the ModuleNotFoundError for module {match}. Add the missing dependency if needed. Context:\n{context}",
        "syntax_error": f"Fix the SyntaxError: {match}. Context:\n{context}",
        "value_error": f"Fix the ValueError: {match}. Context:\n{context}",
        "key_error": f"Fix the KeyError for key {match}. Context:\n{context}",
        "nicegui_error": f"Fix the NiceGUI error: {match}. Context:\n{context}",
        "binding_error": f"Fix the element binding error: {match}. Context:\n{context}",
        "component_error": f"Fix the invalid NiceGUI component: {match}. Context:\n{context}",
        "database_error": f"Fix the database error: {match}. Context:\n{context}",
        "postgres_error": f"Fix the PostgreSQL error: {match}. Context:\n{context}",
        "server_error": f"Fix the server error: {match}. Context:\n{context}",
        "fastapi_error": f"Fix the FastAPI error: {match}. Context:\n{context}",
        "application_error": f"Fix the application error: {match}. Context:\n{context}",
        "databricks_error": f"Fix the Databricks error: {match}. Make the app work without Databricks credentials by using mock data or removing Databricks dependency. Context:\n{context}",
        "auth_error": f"Fix the authentication error: {match}. Make the app work without external credentials by using mock data or local alternatives. Context:\n{context}",
    }
    
    return prompts.get(error_type, f"Fix the error: {match}. Context:\n{context}")


async def apply_fix(client, events, request, fix_prompt, temp_dir, template_id, settings, container_names):
    """Apply a fix using the agent and return updated events/request"""
    logger.info(f"📝 Applying fix: {fix_prompt[:100]}...")
    
    try:
        # Read current files for context
        files_for_snapshot = get_all_files_from_project_dir(temp_dir)
        all_files = [f.model_dump() for f in files_for_snapshot]
        
        # Send fix request to agent
        new_events, new_request = await client.continue_conversation(
            previous_events=events,
            previous_request=request,
            message=fix_prompt,
            all_files=all_files,
            template_id=template_id,
            settings=settings,
        )
        
        # Update events and request for next iteration
        events.extend(new_events)
        
        # Get the diff and apply it
        updated_diff = latest_unified_diff(events)  # Use full events list
        if updated_diff:
            logger.info(f"Generated diff with {len(updated_diff)} characters")
            
            # Don't use template path for applying fixes - apply directly to temp_dir
            success, message = apply_patch(updated_diff, temp_dir, "")
            if success:
                logger.info("✅ Fix applied successfully to filesystem")
                
                # Rebuild and restart the container to apply changes
                logger.info("🔨 Rebuilding Docker container...")
                rebuild_result = subprocess.run(
                    ["docker", "compose", "-p", container_names["project_name"], "build", "app"],
                    cwd=temp_dir,
                    check=False,
                    capture_output=True,
                    text=True
                )
                
                if rebuild_result.returncode != 0:
                    logger.warning(f"Build warning: {rebuild_result.stderr[:500]}")
                
                logger.info("🔄 Restarting Docker container...")
                restart_result = subprocess.run(
                    ["docker", "compose", "-p", container_names["project_name"], "restart", "app"],
                    cwd=temp_dir,
                    check=False,
                    capture_output=True,
                    text=True
                )
                
                if restart_result.returncode == 0:
                    logger.info("✅ Container restarted successfully")
                    # Wait for container to be ready and healthy
                    logger.info("⏳ Waiting for container to be healthy...")
                    container_healthy = await wait_for_healthy_containers(
                        [container_names["app_container_name"]],
                        ["app"],
                        timeout=30,
                        interval=1
                    )
                    if container_healthy:
                        logger.info("✅ Container is healthy after fix")
                        return (True, events, new_request)
                    else:
                        logger.error("Container failed to become healthy after fix")
                        return (False, events, new_request)
                else:
                    logger.error(f"Failed to restart container: {restart_result.stderr[:500]}")
                    return (False, events, new_request)
            else:
                logger.error(f"❌ Failed to apply patch to filesystem: {message}")
                return (False, events, new_request)
        else:
            logger.warning("No diff was generated by agent")
            return (False, events, new_request)
        
    except Exception as e:
        logger.error(f"Error applying fix: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return (False, events, request)


async def run_monitor_existing_project(project_dir: str, prompt: str, template_id=None, use_databricks=False):
    """Monitor an existing project directory and auto-fix errors using edit mode"""
    from api.agent_server.agent_api_client import spawn_local_server, get_all_files_from_project_dir
    
    logger.info(f"Starting monitor mode for existing project: {project_dir}")
    print(f"🔍 Monitor Mode: {project_dir}")
    print("="*50)
    
    # Setup settings for databricks if needed
    settings = {}
    if use_databricks:
        settings = {
            "databricks_host": os.getenv("DATABRICKS_HOST"),
            "databricks_token": os.getenv("DATABRICKS_TOKEN"),
        }
        if not settings["databricks_host"] or not settings["databricks_token"]:
            raise ValueError("Databricks host and token must be set in environment variables to use Databricks")
    
    # Get container names for the project
    container_names = setup_docker_env()
    
    try:
        # Start Docker containers from the existing project
        print("🚀 Starting Docker containers...")
        success, error_message = start_docker_compose(project_dir, container_names["project_name"], build=True)
        if not success:
            logger.error(f"Error starting Docker containers: {error_message}")
            print(f"❌ Failed to start containers: {error_message}")
            print("💡 Tip: Make sure docker-compose.yml exists in the project directory")
            return
        
        # Wait for containers to be healthy
        print("⏳ Waiting for containers to be healthy...")
        container_healthy = await wait_for_healthy_containers(
            [
                container_names["db_container_name"],
                container_names["app_container_name"],
            ],
            ["db", "app"],
            timeout=60,
            interval=1
        )
        
        if not container_healthy:
            print("⚠️ Containers didn't become healthy, but continuing with monitoring...")
        else:
            print("✅ Containers are healthy!")
        
        print("\n📊 App is running on http://localhost:80/")
        print("👀 Monitoring logs for errors...")
        print("🔧 Auto-fix mode enabled using agent")
        print("Press Ctrl+C to stop monitoring\n")
        
        # Start monitoring with auto-fix using agent client
        with spawn_local_server():
            async with AgentApiClient() as client:
                # Read initial files for context
                files_for_snapshot = get_all_files_from_project_dir(project_dir)
                all_files = [f.model_dump() for f in files_for_snapshot]
                
                # Create initial state for monitoring
                monitor_state = {
                    "events": [],
                    "request": None,
                    "client": client,
                    "project_dir": project_dir,
                    "all_files": all_files,
                    "template_id": template_id,
                    "settings": settings,
                    "prompt": prompt
                }
                
                # Run monitoring loop
                await monitor_existing_project_loop(monitor_state, container_names)
                
    except KeyboardInterrupt:
        print("\n🛑 Monitoring stopped by user")
    finally:
        print("🧹 Cleaning up...")
        stop_docker_compose(project_dir, container_names["project_name"])
        print("✅ Cleanup complete")


async def monitor_existing_project_loop(monitor_state, container_names):
    """Monitor loop for existing projects with edit-mode fixes"""
    import re
    
    fixed_errors = set()
    monitoring = True
    consecutive_clean_checks = 0
    max_clean_checks = 5
    
    print("📊 Monitoring Dashboard:")
    print("="*50)
    
    while monitoring:
        try:
            # Adaptive monitoring frequency
            if consecutive_clean_checks >= max_clean_checks:
                await anyio.sleep(5)
            else:
                await anyio.sleep(2)
            
            # Get container logs
            logs = get_container_logs([container_names["app_container_name"]])
            app_logs = logs.get(container_names["app_container_name"], "")
            
            # Detect errors (reuse existing error patterns)
            error_patterns = [
                # Python errors
                (r"AttributeError: '(\w+)' object has no attribute '(\w+)'", "attribute_error"),
                (r"NameError: name '(\w+)' is not defined", "name_error"),
                (r"ImportError: cannot import name '(\w+)' from '([\w.]+)'", "import_error"),
                (r"ImportError: cannot import name '(\w+)'", "import_error"),
                (r"TypeError: (\w+)\(\) missing \d+ required positional argument", "type_error"),
                (r"ModuleNotFoundError: No module named '(\w+)'", "module_error"),
                (r"SyntaxError: (.+)", "syntax_error"),
                (r"ValueError: (.+)", "value_error"),
                (r"KeyError: '(\w+)'", "key_error"),
                # NiceGUI specific errors
                (r"nicegui\.\w+Error: (.+)", "nicegui_error"),
                (r"Failed to bind element: (.+)", "binding_error"),
                (r"Invalid NiceGUI component: (.+)", "component_error"),
                # Database errors
                (r"sqlalchemy\.exc\.\w+: (.+)", "database_error"),
                (r"psycopg2\.\w+: (.+)", "postgres_error"),
                # FastAPI/uvicorn errors
                (r"ERROR:.*uvicorn\.error: (.+)", "server_error"),
                (r"fastapi\.exceptions\.\w+: (.+)", "fastapi_error"),
                # Application startup errors
                (r"ERROR:.*Application startup failed", "startup_error"),
                (r"CRITICAL:.*(.+)", "critical_error"),
                # General ERROR logs (catch-all for any ERROR level)
                (r"- ERROR - (.+)", "application_error"),
                # Databricks specific
                (r"Error executing Databricks query: (.+)", "databricks_error"),
                # Authentication errors
                (r"cannot configure default credentials(.+)", "auth_error"),
            ]
            
            for pattern, error_type in error_patterns:
                matches = re.findall(pattern, app_logs)
                for match in matches:
                    error_key = f"{error_type}:{match}"
                    
                    if error_key not in fixed_errors:
                        consecutive_clean_checks = 0
                        print(f"\n🚨 Error detected: {error_type}")
                        print(f"   Details: {match}")
                        print("   Status: Applying fix...")
                        
                        fixed_errors.add(error_key)
                        
                        # Generate fix prompt
                        fix_prompt = generate_fix_prompt(error_type, match, app_logs)
                        
                        # Apply fix using edit mode approach
                        success = await apply_fix_to_existing_project(
                            monitor_state, 
                            fix_prompt, 
                            container_names
                        )
                        
                        if success:
                            print("   Result: ✅ Fix applied and container restarted")
                        else:
                            print("   Result: ⚠️ Fix attempt completed, monitoring continues")
                        
                        break  # Apply one fix at a time
            
            # Check if app is stable
            error_found = False
            for pattern, _ in error_patterns:
                if re.findall(pattern, app_logs):
                    error_found = True
                    break
            
            # Also check if the web app is actually responding properly
            app_healthy = await check_app_health(monitor_state["project_dir"])
            
            if not error_found and app_healthy:
                consecutive_clean_checks += 1
                if consecutive_clean_checks == 1:
                    print("\n✅ Application running without errors and responding to HTTP")
                elif consecutive_clean_checks == max_clean_checks:
                    print("🎉 Application stable - reducing monitoring frequency")
            elif not app_healthy and not error_found:
                # App not responding but no errors in logs - might be a client-side issue
                print("\n⚠️ App not responding properly but no backend errors detected")
                print("   Checking for client-side or configuration issues...")
                # Force an error to trigger fixing
                error_found = True
                    
        except asyncio.CancelledError:
            monitoring = False
            break
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            await anyio.sleep(5)


async def check_app_health(project_dir: str) -> bool:
    """Check if the app is actually functioning (not just running)"""
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            # Check if we can get the main page
            response = await client.get("http://localhost:80", timeout=5)
            if response.status_code != 200:
                return False
            
            # Check if the page has actual content (not just error page)
            content = response.text
            if "Connection lost" in content or "Error" in content:
                return False
            
            # Check if NiceGUI is loaded
            if "nicegui" not in content.lower():
                return False
                
            return True
    except Exception as e:
        logger.debug(f"Health check failed: {e}")
        return False


async def apply_fix_to_existing_project(monitor_state, fix_prompt, container_names):
    """Apply a fix to an existing project using edit mode approach"""
    from api.agent_server.agent_api_client import apply_patch, latest_unified_diff, get_all_files_from_project_dir
    
    client = monitor_state["client"]
    project_dir = monitor_state["project_dir"]
    template_id = monitor_state["template_id"]
    settings = monitor_state["settings"]
    
    try:
        # Re-read current files for latest context
        files_for_snapshot = get_all_files_from_project_dir(project_dir)
        all_files = [f.model_dump() for f in files_for_snapshot]
        
        # Send fix request to agent (like edit mode)
        if not monitor_state["events"]:
            # First request - initialize conversation
            events, request = await client.send_message(
                fix_prompt,
                template_id=template_id,
                settings=settings,
                all_files=all_files
            )
            monitor_state["events"] = events
            monitor_state["request"] = request
        else:
            # Continue conversation
            new_events, new_request = await client.continue_conversation(
                previous_events=monitor_state["events"],
                previous_request=monitor_state["request"],
                message=fix_prompt,
                all_files=all_files,
                template_id=template_id,
                settings=settings,
            )
            monitor_state["events"].extend(new_events)
            monitor_state["request"] = new_request
        
        # Get and apply the diff
        diff = latest_unified_diff(monitor_state["events"])
        if diff:
            logger.info(f"Generated diff with {len(diff)} characters")
            
            # Apply directly to project directory
            success, message = apply_patch(diff, project_dir, "")
            if success:
                logger.info("✅ Fix applied to project files")
                
                # Restart container
                logger.info("🔄 Restarting container...")
                restart_result = subprocess.run(
                    ["docker", "compose", "-p", container_names["project_name"], "restart", "app"],
                    cwd=project_dir,
                    check=False,
                    capture_output=True,
                    text=True
                )
                
                if restart_result.returncode == 0:
                    await anyio.sleep(3)  # Wait for restart
                    return True
                else:
                    logger.error(f"Failed to restart: {restart_result.stderr[:200]}")
                    return False
            else:
                logger.error(f"Failed to apply patch: {message}")
                return False
        else:
            logger.warning("No diff generated")
            return False
            
    except Exception as e:
        logger.error(f"Error applying fix: {e}")
        return False


if __name__ == "__main__":
    Fire(create_app)
