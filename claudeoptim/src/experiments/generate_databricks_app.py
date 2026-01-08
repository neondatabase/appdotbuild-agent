"""Experiment: Generate a Databricks app using Docker client with MCP server.

This experiment demonstrates how to:
1. Build the Databricks CLI from source using CliBundle
2. Mount the built binary into the Docker container
3. Configure an MCP server using the Databricks CLI's apps-mcp command
4. Use the MCP tools to interact with Databricks
"""

import json
import os
from pathlib import Path
from anyio import run
from sbclient.client import ClaudeClient, DockerConfig
from sbclaude.schema import (
    EvtInterruptModel,
    EvtResultModel,
    EvtErrorModel,
    ResultMessageModel,
)
from databricks.bundle import CliBundle


async def main():
    """Build Databricks CLI and generate app using MCP tools."""
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

    # Docker client configuration
    config = DockerConfig(
        dockerfile_path=Path("Dockerfile.databricks"),
        build_context=Path("."),
        environment={"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")},
        mounted_dirs={
            databrickscfg_path: Path("/home/sbclaude/.databrickscfg"),
            databricksoauth_path: Path("/home/sbclaude/.databricks"),
            built_cli_path: Path("/usr/local/bin/databricks"),
        },
    )

    # MCP server configuration for Databricks apps-mcp
    mcp_servers = {
        "databricks": {
            "type": "stdio",
            "command": "databricks",
            "args": ["experimental", "apps-mcp"],
            "env": {},
        }
    }

    prompt_text = """Using the Databricks MCP tools, create a simple Databricks app
that displays a dashboard showing SQL warehouse information.

Requirements:
- Use the available Databricks MCP tools to interact with Databricks
- List available SQL warehouses and their states
- Create or describe a simple app configuration
"""

    trajectory = None

    print("=" * 60)
    print("Starting Docker client with Databricks MCP server...")
    print("=" * 60)
    print(f"\nPrompt: {prompt_text}\n")

    try:
        async with ClaudeClient(config) as client:
            print("Docker container started successfully!\n")

            async for event in client.prompt(prompt_text, config={"mcp_servers": mcp_servers}):
                print(f"[{event.type}]", end=" ")

                if isinstance(event, EvtInterruptModel):
                    tool_name = event.input_data["tool_name"] if "tool_name" in event.input_data else "unknown"
                    print(f"[{tool_name}] Tool use detected - continuing...")
                    trajectory = event.model_dump()
                    await client.continue_()
                elif isinstance(event, EvtResultModel):
                    print("Completed!")
                    trajectory = event.model_dump()
                    for msg in event.messages:
                        if isinstance(msg, ResultMessageModel):
                            print(f"Duration: {msg.duration_ms}ms (API: {msg.duration_api_ms}ms)")
                            if msg.usage:
                                output_tokens = msg.usage.get("output_tokens", 0)
                                input_tokens = msg.usage.get("input_tokens", 0)
                                print(f"Tokens: {input_tokens} in, {output_tokens} out")
                elif isinstance(event, EvtErrorModel):
                    print(f"Error occurred: {event.detail}")
                    break

    except Exception as e:
        print(f"\nError during execution: {e}")
        if trajectory is None:
            trajectory = {}
        trajectory["exception"] = {"error": str(e), "error_type": type(e).__name__}

    # Save trajectory
    output_path = Path("src/experiments/databricks_trajectory.json")
    with open(output_path, "w") as f:
        json.dump(trajectory, f, indent=2)

    print("\n" + "=" * 60)
    print(f"Trajectory saved to: {output_path}")
    if trajectory:
        print(f"Final event type: {trajectory.get('type', 'unknown')}")
        if trajectory.get("type") == "result":
            print(f"Total messages in history: {len(trajectory.get('messages', []))}")
        elif trajectory.get("exception"):
            print(f"Exception occurred: {trajectory['exception']['error_type']}")
    print("=" * 60)


if __name__ == "__main__":
    print("Starting Databricks MCP experiment...")
    run(main)
