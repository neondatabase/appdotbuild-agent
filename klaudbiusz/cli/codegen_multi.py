import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import coloredlogs
import fire
import litellm
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


@dataclass
class GenerationMetrics:
    cost_usd: float
    input_tokens: int
    output_tokens: int
    turns: int
    app_dir: str | None


class MCPSession:
    def __init__(self, mcp_binary: str | None = None):
        self.mcp_binary = mcp_binary
        self.project_root = Path(__file__).parent.parent.parent
        self.mcp_manifest = self.project_root / "edda" / "edda_mcp" / "Cargo.toml"

        if mcp_binary is None and not self.mcp_manifest.exists():
            raise RuntimeError(f"edda-mcp Cargo.toml not found at {self.mcp_manifest}")

        self._context = None
        self._session_context = None
        self.session: ClientSession | None = None

    async def __aenter__(self) -> ClientSession:
        env = {
            "DATABRICKS_HOST": os.getenv("DATABRICKS_HOST", ""),
            "DATABRICKS_TOKEN": os.getenv("DATABRICKS_TOKEN", ""),
            "DATABRICKS_WAREHOUSE_ID": os.getenv("DATABRICKS_WAREHOUSE_ID", ""),
        }

        if self.mcp_binary:
            server_params = StdioServerParameters(command=self.mcp_binary, args=[], env=env)
        else:
            server_params = StdioServerParameters(
                command="cargo",
                args=["run", "--manifest-path", str(self.mcp_manifest)],
                env=env,
            )

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
        self.app_dir: str | None = None
        self._pending_scaffold_calls: dict[str, str] = {}
        self._sandbox_base_dir: str | None = None

    async def initialize(self):
        tools_list = await self.mcp_session.list_tools()
        mcp_tools = [self._convert_mcp_tool(t) for t in tools_list.tools]
        builtin_tools = self._get_builtin_tools()
        self.tools = mcp_tools + builtin_tools

        if not self.suppress_logs:
            logger.info(f"Loaded {len(self.tools)} tools ({len(mcp_tools)} MCP + {len(builtin_tools)} builtin)")

    def _convert_mcp_tool(self, mcp_tool) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": mcp_tool.name,
                "description": mcp_tool.description or "",
                "parameters": mcp_tool.inputSchema,
            },
        }

    def _get_builtin_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read file contents with line numbers. Default: reads up to 2000 lines from beginning. Lines >2000 chars truncated.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Path to file (relative to app directory)"},
                            "offset": {"type": "number", "description": "Line number to start reading from (1-indexed)"},
                            "limit": {"type": "number", "description": "Number of lines to read (default: 2000)"},
                        },
                        "required": ["file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write content to a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Path to file (relative to app directory)"},
                            "content": {"type": "string", "description": "Content to write"},
                        },
                        "required": ["file_path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": "Edit file by replacing old_string with new_string. Fails if old_string not unique unless replace_all=true.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Path to file (relative to app directory)"},
                            "old_string": {"type": "string", "description": "Exact string to replace (must match exactly including whitespace)"},
                            "new_string": {"type": "string", "description": "Replacement string (must differ from old_string)"},
                            "replace_all": {"type": "boolean", "description": "Replace all occurrences (default: false)"},
                        },
                        "required": ["file_path", "old_string", "new_string"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Execute bash command in app directory. Use for terminal operations (npm, git, etc). Output truncated at 30000 chars.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "Command to execute. Always quote paths with spaces."},
                            "description": {"type": "string", "description": "5-10 word description of what command does"},
                            "timeout": {"type": "number", "description": "Timeout in milliseconds (default: 120000ms)"},
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "grep",
                    "description": "Search file contents with regex. Returns file:line:content by default. Limit results with head_limit.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "Regex pattern to search for"},
                            "path": {"type": "string", "description": "File or directory to search (relative to app directory)"},
                            "case_insensitive": {"type": "boolean", "description": "Case insensitive search (default: false)"},
                            "head_limit": {"type": "number", "description": "Limit output to first N matches"},
                        },
                        "required": ["pattern"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "glob",
                    "description": "Find files matching a glob pattern",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "Glob pattern (e.g., '**/*.ts')"},
                        },
                        "required": ["pattern"],
                    },
                },
            },
        ]

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
                    max_tokens=4096,
                )

                if hasattr(response, "usage") and response.usage:  # type: ignore[attr-defined]
                    total_input_tokens += response.usage.prompt_tokens or 0  # type: ignore[attr-defined]
                    total_output_tokens += response.usage.completion_tokens or 0  # type: ignore[attr-defined]

                if hasattr(response, "_hidden_params") and "response_cost" in response._hidden_params:  # type: ignore[attr-defined]
                    total_cost += response._hidden_params["response_cost"]  # type: ignore[attr-defined]

                choice = response.choices[0]  # type: ignore[attr-defined]
                message = choice.message  # type: ignore[attr-defined]

                if message.content:
                    if not self.suppress_logs:
                        logger.info(f"💬 {message.content}")
                    self.messages.append({"role": "assistant", "content": message.content})

                if message.tool_calls:
                    if not self.suppress_logs:
                        logger.info(f"🔧 Executing {len(message.tool_calls)} tool(s)")

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
                    if not self.suppress_logs:
                        logger.info(f"🏁 Generation complete after {turn} turns")
                    break

                turn += 1

            except Exception as e:
                logger.error(f"❌ Error during generation: {e}")
                raise

        return GenerationMetrics(
            cost_usd=total_cost,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            turns=turn,
            app_dir=self.app_dir,
        )

    def _validate_sandbox_path(self, file_path: str) -> str:
        """Validate that file_path is within sandbox. Returns absolute path or error message."""
        if not self._sandbox_base_dir:
            return "Error: No app directory available. Run scaffold_data_app first."

        base = Path(self._sandbox_base_dir).resolve()
        target = (base / file_path).resolve()

        if not target.is_relative_to(base):
            return f"Error: Access denied. Path {file_path} is outside app directory."

        return str(target)

    async def _execute_builtin_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute builtin file operation tools with sandbox restrictions."""
        import re
        import subprocess

        match tool_name:
            case "read_file":
                file_path = arguments.get("file_path", "")
                validated = self._validate_sandbox_path(file_path)
                if validated.startswith("Error:"):
                    return validated

                try:
                    content = Path(validated).read_text()
                    lines = content.split("\n")

                    offset = arguments.get("offset", 1)
                    limit = arguments.get("limit", 2000)

                    start = int(offset) - 1 if offset else 0
                    end = start + int(limit)
                    selected_lines = lines[start:end]

                    # truncate lines longer than 2000 chars
                    selected_lines = [line[:2000] for line in selected_lines]

                    # cat -n style formatting: right-aligned line numbers
                    numbered = "\n".join(f"{start + i + 1:6d}\t{line}" for i, line in enumerate(selected_lines))
                    return numbered
                except Exception as e:
                    return f"Error reading file: {e}"

            case "write_file":
                file_path = arguments.get("file_path", "")
                content = arguments.get("content", "")
                validated = self._validate_sandbox_path(file_path)
                if validated.startswith("Error:"):
                    return validated

                try:
                    Path(validated).parent.mkdir(parents=True, exist_ok=True)
                    Path(validated).write_text(content)
                    return f"Successfully wrote {len(content)} bytes to {file_path}"
                except Exception as e:
                    return f"Error writing file: {e}"

            case "edit_file":
                file_path = arguments.get("file_path", "")
                old_string = arguments.get("old_string", "")
                new_string = arguments.get("new_string", "")
                replace_all = arguments.get("replace_all", False)
                validated = self._validate_sandbox_path(file_path)
                if validated.startswith("Error:"):
                    return validated

                try:
                    if old_string == new_string:
                        return "Error: old_string and new_string must be different"

                    content = Path(validated).read_text()
                    if old_string not in content:
                        return f"Error: old_string not found in {file_path}"

                    count = content.count(old_string)

                    if not replace_all and count > 1:
                        return f"Error: old_string appears {count} times in {file_path}. Use replace_all=true or provide more context."

                    new_content = content.replace(old_string, new_string)
                    Path(validated).write_text(new_content)

                    occurrences = "all" if replace_all else "1"
                    return f"Successfully replaced {occurrences} occurrence(s) in {file_path}"
                except Exception as e:
                    return f"Error editing file: {e}"

            case "bash":
                command = arguments.get("command", "")
                timeout_ms = arguments.get("timeout", 120000)
                if not self._sandbox_base_dir:
                    return "Error: No app directory available. Run scaffold_data_app first."

                try:
                    result = subprocess.run(
                        command,
                        shell=True,
                        cwd=self._sandbox_base_dir,
                        capture_output=True,
                        text=True,
                        timeout=timeout_ms / 1000,
                    )
                    output = result.stdout + result.stderr

                    # truncate output at 30000 chars per spec
                    if len(output) > 30000:
                        output = output[:30000] + "\n[Output truncated at 30000 characters]"

                    return output if output else f"Command executed (exit code: {result.returncode})"
                except subprocess.TimeoutExpired:
                    return f"Error: Command timed out after {timeout_ms}ms"
                except Exception as e:
                    return f"Error executing command: {e}"

            case "grep":
                pattern = arguments.get("pattern", "")
                path = arguments.get("path", ".")
                case_insensitive = arguments.get("case_insensitive", False)
                head_limit = arguments.get("head_limit")
                validated = self._validate_sandbox_path(path)
                if validated.startswith("Error:"):
                    return validated

                try:
                    matches = []
                    target_path = Path(validated)

                    if target_path.is_file():
                        files = [target_path]
                    else:
                        files = list(target_path.rglob("*"))
                        files = [f for f in files if f.is_file()]

                    flags = re.IGNORECASE if case_insensitive else 0
                    regex = re.compile(pattern, flags)

                    for file in files:
                        try:
                            content = file.read_text()
                            for i, line in enumerate(content.split("\n"), 1):
                                if regex.search(line):
                                    rel_path = file.relative_to(self._sandbox_base_dir or "")
                                    matches.append(f"{rel_path}:{i}: {line}")
                                    if head_limit and len(matches) >= head_limit:
                                        break
                        except Exception:
                            continue

                        if head_limit and len(matches) >= head_limit:
                            break

                    return "\n".join(matches) if matches else "No matches found"
                except Exception as e:
                    return f"Error searching: {e}"

            case "glob":
                pattern = arguments.get("pattern", "")
                if not self._sandbox_base_dir:
                    return "Error: No app directory available. Run scaffold_data_app first."

                try:
                    base = Path(self._sandbox_base_dir)
                    matches = list(base.glob(pattern))
                    rel_matches = [str(m.relative_to(base)) for m in matches]
                    return "\n".join(sorted(rel_matches)) if rel_matches else "No files matched pattern"
                except Exception as e:
                    return f"Error finding files: {e}"

            case _:
                return f"Error: Unknown builtin tool {tool_name}"

    async def _execute_tools(self, tool_calls) -> list[dict[str, Any]]:
        results = []
        builtin_tools = {"read_file", "write_file", "edit_file", "bash", "grep", "glob"}

        for tc in tool_calls:
            tool_name = tc.function.name
            if isinstance(tc.function.arguments, str):
                import json

                arguments = json.loads(tc.function.arguments)
            else:
                arguments = tc.function.arguments

            if not self.suppress_logs:
                logger.info(f"   → {tool_name}({', '.join(f'{k}={v}' for k, v in arguments.items())})")

            if tool_name == "scaffold_data_app" and "work_dir" in arguments:
                self._pending_scaffold_calls[tc.id] = arguments["work_dir"]

            try:
                if tool_name in builtin_tools:
                    content = await self._execute_builtin_tool(tool_name, arguments)
                else:
                    result = await self.mcp_session.call_tool(tool_name, arguments)

                    if tc.id in self._pending_scaffold_calls:
                        self.app_dir = self._pending_scaffold_calls.pop(tc.id)
                        self._sandbox_base_dir = self.app_dir

                    content = str(result.content[0].text if result.content else "")  # type: ignore[attr-defined]

                if not self.suppress_logs:
                    truncated = content[:200] + "..." if len(content) > 200 else content
                    logger.info(f"   ✅ {truncated}")

                results.append({"role": "tool", "tool_call_id": tc.id, "content": content})

            except Exception as e:
                error_msg = f"Error: {e}"
                if not self.suppress_logs:
                    logger.warning(f"   ❌ {error_msg}")

                results.append({"role": "tool", "tool_call_id": tc.id, "content": error_msg})

        return results


class MultiProviderAppBuilder:
    def __init__(
        self,
        app_name: str,
        model: str = "gpt-4-turbo",
        mcp_binary: str | None = None,
        suppress_logs: bool = False,
    ):
        self.app_name = app_name
        self.model = model
        self.mcp_binary = mcp_binary
        self.suppress_logs = suppress_logs
        litellm.drop_params = True

    def _setup_logging(self) -> None:
        if self.suppress_logs:
            logging.getLogger().setLevel(logging.ERROR)
        else:
            coloredlogs.install(level="INFO")

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
3. Call scaffold_data_app with the app specification
4. Use validate_data_app to check the generated code

## File Operations & Tool Usage

You have access to file operation tools for working with generated apps:
- **read_file**: Read file contents with line numbers (default 2000 lines, truncates at 2000 chars/line)
- **write_file**: Create new files (use Edit for existing files)
- **edit_file**: Replace exact strings in files (fails if not unique unless replace_all=true)
- **bash**: Execute terminal commands (npm, git, etc) - always quote paths with spaces
- **grep**: Search file contents with regex (use case_insensitive and head_limit as needed)
- **glob**: Find files by pattern (e.g., "**/*.ts")

Tool Selection Guidelines:
- ✅ Use specialized tools (Read/Write/Edit/Grep/Glob) for file operations
- ❌ Never use bash for file operations (cat, echo >, sed, awk, find, grep)
- ✅ Use bash only for terminal operations (npm install, npm test, git, etc)
- ✅ Prefer Edit over Write for existing files
- ✅ Use head_limit with Grep to avoid overwhelming output

All file operations are restricted to the app directory for security.

Be concise and to the point."""

    async def run_async(self, prompt: str) -> GenerationMetrics:
        self._setup_logging()

        async with MCPSession(self.mcp_binary) as session:
            system_prompt = self._build_system_prompt()

            agent = LiteLLMAgent(
                model=self.model,
                mcp_session=session,
                system_prompt=system_prompt,
                suppress_logs=self.suppress_logs,
            )
            await agent.initialize()

            # get current dir
            local_dir = Path(__file__).parent.resolve()
            full_app_dir = local_dir / "app" / self.app_name
            user_prompt = f"App name: {self.app_name}\nApp directory: {full_app_dir}\n\nTask: {prompt}"
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

    def run(self, prompt: str) -> GenerationMetrics:
        return asyncio.run(self.run_async(prompt))


def cli(
    prompt: str,
    app_name: str | None = None,
    # model: str = "gemini/gemini-2.5-pro",
    model: str = "openrouter/minimax/minimax-m2",
    suppress_logs: bool = False,
    mcp_binary: str | None = None,
):
    if app_name is None:
        app_name = f"app-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    builder = MultiProviderAppBuilder(
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
