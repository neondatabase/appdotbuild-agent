import os
import subprocess
import random
import string
import docker
from docker.errors import NotFound
import anyio
from typing import Dict, List, Optional, Tuple
from log import get_logger

logger = get_logger(__name__)

def generate_random_name(prefix: str, length: int = 8) -> str:
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
    return f"{prefix}-{suffix}"

def setup_docker_env(project_name: Optional[str] = None) -> Dict[str, str]:
    if not project_name:
        project_name = generate_random_name("project")

    # Generate container names
    container_names = {
        "db_container_name": generate_random_name("postgres"),
        "app_container_name": generate_random_name("app"),
        "db_push_container_name": generate_random_name("db-push"),
        "network_name": generate_random_name("network"),
        "project_name": project_name
    }

    os.environ["POSTGRES_CONTAINER_NAME"] = container_names["db_container_name"]
    os.environ["BACKEND_CONTAINER_NAME"] = container_names["app_container_name"]
    os.environ["DB_PUSH_CONTAINER_NAME"] = container_names["db_push_container_name"]
    os.environ["NETWORK_NAME"] = container_names["network_name"]
    return container_names

def start_docker_compose(
    project_dir: str,
    project_name: str,
    build: bool = False
) -> Tuple[bool, str]:
    logger.info(f"Starting Docker containers in {project_dir}")

    # Build containers if requested
    if build:
        try:
            logger.info("Building Docker containers")
            subprocess.run(
                ["docker", "compose", "build"],
                cwd=project_dir,
                check=True
            )
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to build Docker containers: return code {e.returncode}"
            logger.error(error_msg)
            return False, error_msg

    # Ensure clean environment
    try:
        subprocess.run(
            ["docker", "compose", "-p", project_name, "down", "-v", "--remove-orphans"],
            cwd=project_dir,
            check=False,
            capture_output=True
        )
    except Exception as e:
        logger.warning(f"Error cleaning up before start: {e}")

    # Start containers
    try:
        res = subprocess.run(
            ["docker", "compose", "-p", project_name, "up", "-d"],
            cwd=project_dir,
            check=False,
            capture_output=True,
            text=True
        )

        if res.returncode != 0:
            error_msg = f"Failed to start Docker containers: return code {res.returncode}, stderr: {res.stderr}"
            print(res.stdout)
            logger.error(error_msg)
            return False, error_msg

        return True, ""
    except Exception as e:
        error_msg = f"Error starting Docker containers: {str(e)}"
        logger.exception(error_msg)
        return False, error_msg

async def wait_for_healthy_containers(
    container_names: List[str],
    container_types: List[str],
    timeout: int = 30,
    interval: int = 1
) -> bool:
    docker_cli = docker.from_env()
    start_time = anyio.current_time()

    try:
        while anyio.current_time() - start_time < timeout:
            all_healthy = True
            for name, kind in zip(container_names, container_types):
                try:
                    container = docker_cli.containers.get(name)
                    if container.status != "running":
                        logger.info(f"{kind} container is not running yet: {container.status}")
                        all_healthy = False
                        break

                    health_status = container.attrs.get('State', {}).get('Health', {}).get('Status')
                    if health_status != 'healthy':
                        logger.info(f"{kind} container is not healthy yet: {health_status}")
                        all_healthy = False
                        break
                    logger.info(f"{kind} container is healthy.")
                except NotFound:
                    logger.info(f"{kind} container not found")
                    all_healthy = False
                    break
                except Exception:
                    logger.exception(f"Error checking container {name} status")
                    all_healthy = False
                    break

            if all_healthy:
                logger.info("All containers are healthy.")
                return True

            await anyio.sleep(interval)

        logger.error(f"Containers did not become healthy within {timeout} seconds")
        return False
    except Exception as e:
        logger.exception(f"Error waiting for containers: {e}")
        return False

def stop_docker_compose(
    project_dir: str,
    project_name: Optional[str] = None
) -> None:
    try:
        cmd = ["docker", "compose", "down", "-v", "--remove-orphans"]
        if project_name:
            cmd = ["docker", "compose", "-p", project_name, "down", "-v", "--remove-orphans"]

        logger.info(f"Stopping Docker containers for project {project_name} in {project_dir}")
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            check=False,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            logger.error(f"Failed to stop Docker containers: {result.stderr}")
    except Exception as e:
        logger.exception(f"Error stopping Docker containers: {e}")

def get_container_logs(
    container_names: List[str],
    lines: int = 50
) -> Dict[str, str]:
    docker_cli = docker.from_env()
    logs = {}

    for name in container_names:
        try:
            container = docker_cli.containers.get(name)
            logs[name] = container.logs(tail=lines).decode('utf-8')
        except Exception as e:
            logger.exception(f"Error getting logs for container {name}")
            logs[name] = f"Error: {str(e)}"

    return logs
