#!/usr/bin/env python3
"""Example usage of ClaudeDockerClient with a custom-built Databricks CLI.

This example demonstrates how to:
1. Build the Databricks CLI from source using CliBundle
2. Mount the built binary into the Docker container
3. Use it with credentials mounted from the host system

To build the Docker image, use the provided Dockerfile.databricks.
```bash
docker build -t sbclaude .
```
"""

import anyio
import os
from pathlib import Path
from sbclient import ClaudeClient, DockerConfig
from sbclaude.schema import EvtInterruptModel, EvtResultModel, EvtErrorModel
from databricks.bundle import CliBundle


async def main():
    """Build Databricks CLI and run a prompt to list warehouses."""
    # Path to databricks config on host
    databrickscfg_path = Path.home() / ".databrickscfg"

    if not databrickscfg_path.exists():
        print(f"Error: {databrickscfg_path} not found.")
        print("Please configure Databricks CLI first: databricks configure")
        return

    # Path to oauth2 token file (if used)
    databricksoauth_path = Path.home() / ".databricks"

    if not databricksoauth_path.exists():
        print(f"Error: {databricksoauth_path} not found.")
        print("If you are using OAuth2 tokens, please ensure this file exists.")
        return

    # Build the Databricks CLI from source
    print("Building Databricks CLI from source...")
    builder = CliBundle(cli_repo_url="https://github.com/databricks/cli")
    build_output = builder.build()
    print("Build output:\n", build_output)

    # The built binary is at builder.tmp_dir / "cli"
    built_cli_path = builder.tmp_dir / "cli"

    if not built_cli_path.exists():
        print(f"Error: Built CLI not found at {built_cli_path}")
        return

    print(f"CLI built successfully at: {built_cli_path}")

    config = DockerConfig(
        dockerfile_path=Path("Dockerfile"),
        build_context=Path("."),
        environment={"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")},
        mounted_dirs={
            databrickscfg_path: Path("/home/sbclaude/.databrickscfg"),
            databricksoauth_path: Path("/home/sbclaude/.databricks"),
            built_cli_path: Path("/usr/local/bin/databricks"), # mount built CLI
        },
    )

    async with ClaudeClient(config) as client:
        prompt = "Use the databricks CLI to list all available SQL warehouses. Show me the warehouse names and their current state."
        print(f"Prompt: {prompt}\n")
        print("-" * 50)

        async for event in client.prompt(prompt):
            if isinstance(event, EvtInterruptModel):
                print(f"[Interrupt] Tool: {event.tool_use_id}")
                await client.continue_()
            elif isinstance(event, EvtResultModel):
                print("-" * 50)
                print(f"[Result] Completed with {len(event.messages)} messages")
                for msg in event.messages:
                    print(msg)
            elif isinstance(event, EvtErrorModel):
                print(f"[Error] {event.detail}")


if __name__ == "__main__":
    anyio.run(main)
