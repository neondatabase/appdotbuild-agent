import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import fire
import litellm
from dotenv import load_dotenv
from cli.utils.litellm_multiprocess_fix import patch_litellm_for_multiprocessing
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from cli.utils.shared import ScaffoldTracker, Tracker, build_mcp_command, setup_logging, validate_mcp_manifest

patch_litellm_for_multiprocessing()

logger = logging.getLogger(__name__)


@dataclass
class GenerationMetrics:
    cost_usd: float
    input_tokens: int
    output_tokens: int
    turns: int
    app_dir: str | None


class MCPSession:
    def __init__(self, mcp_binary: str | None = None, mcp_json_path: str | None = None):
        self.mcp_binary = mcp_binary
        self.mcp_json_path = mcp_json_path
        self.project_root = Path(__file__).parent.parent.parent
        self.mcp_manifest = validate_mcp_manifest(mcp_binary, self.project_root)

        self._context = None
        self._session_context = None
        self.session: ClientSession | None = None

    async def __aenter__(self) -> ClientSession:
        env = {
            "DATABRICKS_HOST": os.getenv("DATABRICKS_HOST", ""),
            "DATABRICKS_TOKEN": os.getenv("DATABRICKS_TOKEN", ""),
            "DATABRICKS_WAREHOUSE_ID": os.getenv("DATABRICKS_WAREHOUSE_ID", ""),
        }

        command, args = build_mcp_command(self.mcp_binary, self.mcp_manifest, self.mcp_json_path)
        # add workspace tools flag for LiteLLM backend (works for both binary and cargo run)
        # only if not using JSON override
        if not self.mcp_json_path:
            args.append("--with-workspace-tools=true")
        server_params = StdioServerParameters(command=command, args=args, env=env)

        self._context = stdio_client(server_params)
        read, write = await self._context.__aenter__()

        self._session_context = ClientSession(read, write)
        self.session = await self._session_context.__aenter__()
        await self.session.initialize()

        return self.session

    async def __aexit__(self, *args):
        if self._session_context:
            await self._session_context.__aexit__(*args)
        if self._context:
            await self._context.__aexit__(*args)


class LiteLLMAgent:
    def __init__(
        self,
        model: str,
        mcp_session: ClientSession,
        system_prompt: str,
        app_name: str,
        max_turns: int = 75,
        temperature: float = 0.7,
        suppress_logs: bool = False,
    ):
        self.model = model
        self.mcp_session = mcp_session
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.temperature = temperature
        self.suppress_logs = suppress_logs
        self.messages: list[dict[str, Any]] = []
        self.tools: list[dict[str, Any]] = []
        self.tracker = Tracker(uuid4(), app_name, suppress_logs)
        self.scaffold_tracker = ScaffoldTracker()

    async def initialize(self):
        tools_list = await self.mcp_session.list_tools()
        self.tools = [self._convert_mcp_tool(t) for t in tools_list.tools]

        if not self.suppress_logs:
            logger.info(f"Loaded {len(self.tools)} MCP tools")

    def _clean_schema_for_databricks(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Remove JSON schema fields that Databricks serving doesn't support."""
        if not isinstance(schema, dict):
            return schema

        cleaned = {}
        for key, value in schema.items():
            if key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
                if schema.get("type") == "integer":
                    continue

            if key == "input_examples":
                continue

            if isinstance(value, dict):
                cleaned[key] = self._clean_schema_for_databricks(value)
            elif isinstance(value, list):
                cleaned[key] = [
                    self._clean_schema_for_databricks(item) if isinstance(item, dict) else item for item in value
                ]
            else:
                cleaned[key] = value

        return cleaned

    def _convert_mcp_tool(self, mcp_tool) -> dict[str, Any]:
        parameters = self._clean_schema_for_databricks(mcp_tool.inputSchema)
        return {
            "type": "function",
            "function": {
                "name": mcp_tool.name,
                "description": mcp_tool.description or "",
                "parameters": parameters,
            },
        }

    async def run(self, user_prompt: str) -> GenerationMetrics:
        self.messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        turn = 0
        total_cost = 0.0
        total_input_tokens = 0
        total_output_tokens = 0

        if not self.suppress_logs:
            logger.info(f"\n{'=' * 80}")
            logger.info(f"Starting generation with model: {self.model}")
            logger.info(f"{'=' * 80}\n")

        while turn < self.max_turns:
            try:
                response = await litellm.acompletion(
                    model=self.model,
                    messages=self.messages,
                    tools=self.tools if self.tools else None,
                    temperature=self.temperature,
                    max_tokens=8192,  # increased to handle longer tool arguments
                )

                if hasattr(response, "usage") and response.usage:  # type: ignore[attr-defined]
                    total_input_tokens += response.usage.prompt_tokens or 0  # type: ignore[attr-defined]
                    total_output_tokens += response.usage.completion_tokens or 0  # type: ignore[attr-defined]

                if hasattr(response, "_hidden_params") and "response_cost" in response._hidden_params:  # type: ignore[attr-defined]
                    cost = response._hidden_params["response_cost"]  # type: ignore[attr-defined]
                    if cost is not None:
                        total_cost += cost

                choice = response.choices[0]  # type: ignore[attr-defined]
                message = choice.message  # type: ignore[attr-defined]

                if message.content:
                    self.tracker.log_text("assistant", message.content)
                    self.messages.append({"role": "assistant", "content": message.content})

                if message.tool_calls:
                    if not self.suppress_logs:
                        logger.info(f"🔧 Executing {len(message.tool_calls)} tool(s)")

                    # log each tool call via tracker
                    for tc in message.tool_calls:
                        if isinstance(tc.function.arguments, str):
                            args = json.loads(tc.function.arguments)
                        else:
                            args = tc.function.arguments
                        self.tracker.log_tool_call(tc.function.name or "unknown", args, tc.id)

                    self.messages.append(
                        {
                            "role": "assistant",
                            "content": message.content,
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                                }
                                for tc in message.tool_calls
                            ],
                        }
                    )

                    tool_results = await self._execute_tools(message.tool_calls)
                    for result in tool_results:
                        self.messages.append(result)

                    turn += 1
                    continue

                if choice.finish_reason == "stop":
                    self.tracker.log_session_complete(
                        turns=turn,
                        cost_usd=total_cost,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                    )
                    break

                turn += 1

            except Exception as e:
                logger.error(f"❌ Error during generation: {e}")
                raise

        # Save generation_metrics.json to app directory for evaluation
        if self.scaffold_tracker.app_dir:
            metrics_file = Path(self.scaffold_tracker.app_dir) / "generation_metrics.json"
            metrics_file.write_text(json.dumps({
                "cost_usd": total_cost,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "turns": turn,
            }, indent=2))

        return GenerationMetrics(
            cost_usd=total_cost,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            turns=turn,
            app_dir=self.scaffold_tracker.app_dir,
        )

    async def _execute_tools(self, tool_calls) -> list[dict[str, Any]]:
        results = []

        for tc in tool_calls:
            tool_name = tc.function.name
            if isinstance(tc.function.arguments, str):
                arguments = json.loads(tc.function.arguments)
            else:
                arguments = tc.function.arguments

            if not self.suppress_logs:
                logger.info(f"   → {tool_name}({', '.join(f'{k}={v}' for k, v in arguments.items())})")

            if tool_name == "scaffold_data_app" and "work_dir" in arguments:
                self.scaffold_tracker.track(tc.id, arguments["work_dir"])

            try:
                result = await self.mcp_session.call_tool(tool_name, arguments)
                self.scaffold_tracker.resolve(tc.id)

                content = str(result.content[0].text if result.content else "")  # type: ignore[attr-defined]
                self.tracker.log_tool_result(tc.id, content, is_error=False)
                results.append({"role": "tool", "tool_call_id": tc.id, "content": content})

            except Exception as e:
                error_msg = f"Error: {e}"
                self.tracker.log_tool_result(tc.id, error_msg, is_error=True)
                results.append({"role": "tool", "tool_call_id": tc.id, "content": error_msg})

        return results


class LiteLLMAppBuilder:
    def __init__(
        self,
        app_name: str,
        model: str,
        mcp_binary: str | None = None,
        mcp_json_path: str | None = None,
        suppress_logs: bool = False,
        output_dir: str | None = None,
    ):
        self.app_name = app_name
        self.model = model
        self.mcp_binary = mcp_binary
        self.mcp_json_path = mcp_json_path
        self.suppress_logs = suppress_logs
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / "app"
        litellm.drop_params = True

    def _build_system_prompt(self) -> str:
        return """You are an AI assistant that builds Databricks data applications.

Your primary tool is `scaffold_data_app` which creates a full-stack TypeScript application with:
- React frontend with data visualization
- Express backend API
- Databricks SQL integration
- Modern UI components

When asked to create an app:
1. Use databricks_* tools to explore available data (catalogs, schemas, tables)
2. Design appropriate queries for the use case
3. Call scaffold_data_app to start with a well-tested template
4. Use workspace tools (read_file, write_file, edit_file, grep, glob) to build out the requested app features
4. Use validate_data_app to check the generated code passes the build, tests, linters

## File Operations & Tool Usage

You have access to file operation tools for working with generated apps:
- **read_file**: Read file contents with line numbers (default 2000 lines, truncates at 2000 chars/line)
- **write_file**: Create new files (use Edit for existing files)
- **edit_file**: Replace exact strings in files (fails if not unique unless replace_all=true)
- **grep**: Search file contents with regex (use case_insensitive and head_limit as needed)
- **glob**: Find files by pattern (e.g., "**/*.ts")
- **bash**: Execute terminal commands (npm, git, etc) - always quote paths with spaces. Usually you don't need bash, this is for the situations where something is wrong.

Tool Selection Guidelines:
- ✅ Use specialized tools (Read/Write/Edit/Grep/Glob) for file operations
- ❌ Never use bash for file operations (cat, echo >, sed, awk, find, grep)
- ✅ Use bash only for terminal operations (npm install, npm test, git, etc)
- ✅ Prefer Edit over Write for existing files
- ✅ Use head_limit with Grep to avoid overwhelming output

All file operations are restricted to the app directory for security.

Be concise and to the point."""

    async def run_async(self, prompt: str) -> GenerationMetrics:
        setup_logging(self.suppress_logs, self.mcp_binary)

        mcp_session = MCPSession(self.mcp_binary, self.mcp_json_path)
        agent = None
        metrics = None

        try:
            session = await mcp_session.__aenter__()

            system_prompt = self._build_system_prompt()

            agent = LiteLLMAgent(
                model=self.model,
                mcp_session=session,
                system_prompt=system_prompt,
                app_name=self.app_name,
                suppress_logs=self.suppress_logs,
            )
            await agent.initialize()

            # compute absolute path for MCP tool (scaffold_data_app requires absolute path)
            app_dir = self.output_dir / self.app_name
            user_prompt = f"App name: {self.app_name}\nApp directory: {app_dir}\n\nTask: {prompt}"
            metrics = await agent.run(user_prompt)

            if not self.suppress_logs:
                logger.info(f"\n{'=' * 80}")
                logger.info(f"Cost: ${metrics.cost_usd:.4f}")
                logger.info(f"Tokens: {metrics.input_tokens} in, {metrics.output_tokens} out")
                logger.info(f"Turns: {metrics.turns}")
                if metrics.app_dir:
                    logger.info(f"App directory: {metrics.app_dir}")
                logger.info(f"{'=' * 80}\n")

            return metrics
        finally:
            # save trajectory via tracker (if agent and metrics were initialized)
            if agent is not None and metrics is not None:
                await agent.tracker.save(
                    prompt=prompt,
                    cost_usd=metrics.cost_usd,
                    total_tokens=metrics.input_tokens + metrics.output_tokens,
                    turns=metrics.turns,
                    backend="litellm",
                    model=self.model,
                    app_dir=metrics.app_dir,
                )
            # explicitly cleanup to avoid asyncio context issues with multiprocessing
            try:
                await mcp_session.__aexit__(None, None, None)
            except Exception:
                pass  # suppress cleanup errors in multiprocessing

    def run(self, prompt: str) -> GenerationMetrics:
        return asyncio.run(self.run_async(prompt))


def cli(
    prompt: str,
    app_name: str | None = None,
    model: str = "openrouter/minimax/minimax-m2",  # other good options: "openrouter/moonshotai/kimi-k2-thinking",  "gemini/gemini-2.5-pro",
    # some open-weights platform provide openai/anthropic-like API that can be used like
    # OPENAI_API_KEY=$DATABRICKS_TOKEN OPENAI_API_BASE=https://$DATABRICKS_HOST/serving-endpoints uv run cli/single_run.py "..." --backend=litellm --model="openai/databricks-gpt-oss-120b"
    # OPENAI_API_BASE="https://api.minimax.io/v1" OPENAI_API_KEY="$MINIMAX_API_KEY" uv run cli/single_run.py "..."" --backend=litellm --model="openai/MiniMax-M2"
    # ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic" ANTHROPIC_API_KEY="$MINIMAX_API_KEY" uv run cli/single_run.py "..." --backend=litellm --model="anthropic/MiniMax-M2"
    suppress_logs: bool = False,
    mcp_binary: str | None = None,
):
    if app_name is None:
        app_name = f"app-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    builder = LiteLLMAppBuilder(
        app_name=app_name,
        model=model,
        mcp_binary=mcp_binary,
        suppress_logs=suppress_logs,
    )
    metrics = builder.run(prompt)
    print(f"\n{'=' * 80}")
    print("Final metrics:")
    print(f"  Cost: ${metrics.cost_usd:.4f}")
    print(f"  Turns: {metrics.turns}")
    print(f"  Tokens: {metrics.input_tokens} in, {metrics.output_tokens} out")
    print(f"  App dir: {metrics.app_dir or 'NOT CAPTURED'}")
    print(f"{'=' * 80}\n")
    return {
        "cost_usd": metrics.cost_usd,
        "turns": metrics.turns,
        "input_tokens": metrics.input_tokens,
        "output_tokens": metrics.output_tokens,
        "app_dir": metrics.app_dir,
    }


if __name__ == "__main__":
    load_dotenv()
    fire.Fire(cli)
