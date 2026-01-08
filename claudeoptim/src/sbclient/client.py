"""Docker client for sbclaude service."""

from typing import AsyncIterator, Any
from dataclasses import dataclass, field
from pathlib import Path
import anyio
import os
import shutil
import tempfile
import docker
import websockets
from sbclaude.schema import (
    CmdPromptModel,
    CmdContinueModel,
    CmdStopModel,
    EventModel,
    EvtInterruptModel,
    EvtResultModel,
    EvtErrorModel,
)


@dataclass
class DockerConfig:
    image_name: str = "sbclaude:latest"
    base_port: int = 8000
    dockerfile_path: Path | None = None
    build_context: Path | None = None
    readiness_timeout: float = 30.0
    environment: dict[str, str] = field(default_factory=dict)
    mounted_dirs: dict[Path, Path] = field(default_factory=dict)  # host_path -> container_path (files or dirs)


def _copy_to_temp(host_path: Path) -> Path:
    """Copy a file or directory to a temporary location.

    Args:
        host_path: Path to the source file or directory on the host.

    Returns:
        Path to the temporary copy.
    """
    if host_path.is_dir():
        temp_path = Path(tempfile.mkdtemp())
        shutil.copytree(host_path, temp_path, dirs_exist_ok=True)
    else:
        fd, temp_file = tempfile.mkstemp(suffix=host_path.suffix)
        os.close(fd)
        temp_path = Path(temp_file)
        shutil.copy2(host_path, temp_path)
    return temp_path


class ClaudeClient:
    def __init__(self, config: DockerConfig = DockerConfig()):
        self.config = config
        self.docker_client = docker.from_env()
        self.container = None
        self.websocket = None
        self.host_port: int | None = None
        self._temp_paths: list[Path] = []

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def start(self):
        """Start container and connect to WebSocket."""
        self._start_container()
        await self._wait_for_ready()
        await self._connect()

    async def stop(self):
        """Stop and remove container."""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None

        if self.container:
            self.container.remove(force=True)
            self.container = None

        # Clean up temp files and directories
        for temp_path in self._temp_paths:
            if temp_path.is_dir():
                shutil.rmtree(temp_path, ignore_errors=True)
            else:
                temp_path.unlink(missing_ok=True)
        self._temp_paths.clear()

    def _start_container(self):
        """Start container with port mapping, environment variables, and volume mounts."""
        base_port = f"{self.config.base_port}/tcp"

        volumes = {}
        for host_path, container_path in self.config.mounted_dirs.items():
            temp_path = _copy_to_temp(host_path)
            self._temp_paths.append(temp_path)
            volumes[str(temp_path)] = {"bind": str(container_path), "mode": "rw"}

        self.container = self.docker_client.containers.run(
            image=self.config.image_name,
            detach=True,
            ports={base_port: None},
            environment=self.config.environment,
            volumes=volumes if volumes else None,
        )

        self.container.reload()
        mapped_port = self.container.ports.get(base_port)
        if not mapped_port:
            raise RuntimeError("Failed to map container port")
        self.host_port = int(mapped_port[0]['HostPort'])


    async def _wait_for_ready(self):
        """Wait for service to be ready."""
        start_time = anyio.current_time()
        while anyio.current_time() - start_time < self.config.readiness_timeout:
            try:
                ws_url = f"ws://localhost:{self.host_port}/ws"
                async with websockets.connect(ws_url):
                    return
            except (OSError, websockets.exceptions.WebSocketException):
                await anyio.sleep(0.5)
        raise TimeoutError("Service did not become ready in time")

    async def _connect(self):
        """Connect to WebSocket endpoint."""
        ws_url = f"ws://localhost:{self.host_port}/ws"
        self.websocket = await websockets.connect(ws_url)

    async def prompt(self, text: str, config: dict[str, Any] | None = None) -> AsyncIterator[EvtInterruptModel | EvtResultModel | EvtErrorModel]:
        """
        Send prompt and yield events until EvtResult or connection closes.

        Args:
            text: Prompt text
            config: Optional configuration for ClaudeRunner

        Yields:
            Event models (EvtInterruptModel, EvtResultModel, or EvtErrorModel)
        """
        if not self.websocket:
            raise RuntimeError("Not connected. Call start() first.")

        cmd = CmdPromptModel(prompt=text, config=config)
        await self.websocket.send(cmd.model_dump_json())

        while True:
            try:
                response = await self.websocket.recv()
                event = EventModel.model_validate_json(response).root
                yield event
                if isinstance(event, (EvtResultModel, EvtErrorModel)):
                    break
            except websockets.exceptions.ConnectionClosed:
                break

    async def continue_(self):
        """Send continue command."""
        if not self.websocket:
            raise RuntimeError("Not connected. Call start() first.")
        cmd = CmdContinueModel()
        await self.websocket.send(cmd.model_dump_json())

    async def stop_execution(self):
        """Send stop command."""
        if not self.websocket:
            raise RuntimeError("Not connected. Call start() first.")
        cmd = CmdStopModel()
        await self.websocket.send(cmd.model_dump_json())


async def main():
    """Example usage."""
    config = DockerConfig(
        dockerfile_path=Path("Dockerfile"),
        build_context=Path("."),
        environment={"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")},
    )

    async with ClaudeClient(config) as client:
        prompt_text = "Create a file called test.txt with content 'Hello from Docker!'"
        print(f"Sending prompt: {prompt_text}")

        async for event in client.prompt(prompt_text):
            print(f"Event: {event.type}")
            if isinstance(event, EvtInterruptModel):
                print("Continuing...")
                await client.continue_()
            elif isinstance(event, EvtResultModel):
                print("Completed!")
            elif isinstance(event, EvtErrorModel):
                print(f"Error: {event.detail}")


if __name__ == "__main__":
    anyio.run(main)
