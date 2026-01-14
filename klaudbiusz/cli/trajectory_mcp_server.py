"""MCP server providing custom trajectory analysis tool.

This server is spawned as a subprocess by analyze_trajectories.py to provide
the analyze_trajectories tool to the Claude agent.
"""

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import litellm
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


@dataclass
class AnalysisConfig:
    trajectory_data: list[tuple[str, str]]
    map_model: str


async def analyze_single_trajectory(trajectory_md: str, app_name: str, model: str, custom_prompt: str) -> str:
    """Analyze a single trajectory using LLM."""
    prompt = f"""{custom_prompt}

App: {app_name}

{trajectory_md}"""

    response = await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=8 * 1024,
    )

    return response.choices[0].message.content or ""  # type: ignore[union-attr]


async def run_custom_map_phase(custom_prompt: str, config: AnalysisConfig) -> str:
    """Run a custom map phase over all trajectories."""
    tasks = [
        analyze_single_trajectory(trajectory_md, app_name, config.map_model, custom_prompt)
        for app_name, trajectory_md in config.trajectory_data
    ]

    results = await asyncio.gather(*tasks)
    analyses = list(zip([name for name, _ in config.trajectory_data], results))

    return "\n\n".join([f"## {app_name}\n\n{analysis}" for app_name, analysis in analyses])


def create_server(config: AnalysisConfig) -> Server:
    """Create MCP server with the given config."""
    server = Server("trajectory-analyzer")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="analyze_trajectories",
                description=(
                    "Run a custom analysis over all agent trajectories using your prompt. "
                    "Use this to extract specific patterns, investigate hypotheses, or gather "
                    "detailed information not captured in the initial analysis. "
                    "Your prompt will be sent to each trajectory individually and results aggregated."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "The analysis prompt to run on each trajectory.",
                        },
                    },
                    "required": ["prompt"],
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name != "analyze_trajectories":
            raise ValueError(f"Unknown tool: {name}")

        prompt = arguments.get("prompt", "")
        result = await run_custom_map_phase(prompt, config)
        return [TextContent(type="text", text=result)]

    return server


async def main():
    if len(sys.argv) < 2:
        print("Usage: trajectory_mcp_server.py <config_file>", file=sys.stderr)
        sys.exit(1)

    config_path = Path(sys.argv[1])
    raw_config = json.loads(config_path.read_text())
    config = AnalysisConfig(
        trajectory_data=[tuple(item) for item in raw_config["trajectory_data"]],
        map_model=raw_config["map_model"],
    )

    litellm.drop_params = True

    server = create_server(config)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
