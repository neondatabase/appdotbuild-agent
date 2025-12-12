"""Benchmark trigger rate: does the agent use the injected capability (Skill vs MCP)?

Compares both approaches on the same prompts to measure which context injection works better.
Uses ClaudeSDKClient for early stopping once target tool is triggered.
"""

import asyncio
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import fire
from tqdm import tqdm

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    UserMessage,
)
from dotenv import load_dotenv

from cli.prompts import get_prompts
from cli.utils.shared import build_mcp_command, validate_mcp_manifest

load_dotenv()

MAX_TURNS = 10
MODEL: str | None = None  # e.g. "claude-sonnet-4-20250514", None = default


@dataclass
class TrialResult:
    app_name: str
    triggered: bool
    tool_calls: list[str]
    turns: int
    cost_usd: float
    error: str | None
    logs: list[str] = field(default_factory=list)


@dataclass
class BenchmarkResults:
    approach: str
    trials: list[TrialResult] = field(default_factory=list)

    @property
    def trigger_rate(self) -> float:
        if not self.trials:
            return 0.0
        return sum(1 for t in self.trials if t.triggered) / len(self.trials) * 100

    @property
    def error_count(self) -> int:
        return sum(1 for t in self.trials if t.error)

    @property
    def total_cost(self) -> float:
        return sum(t.cost_usd for t in self.trials)

    def tool_distribution(self) -> dict[str, int]:
        dist: dict[str, int] = {}
        for t in self.trials:
            for tc in t.tool_calls:
                dist[tc] = dist.get(tc, 0) + 1
        return dict(sorted(dist.items(), key=lambda x: -x[1]))


def _format_tool(block: ToolUseBlock) -> str:
    """Format tool call for logging."""
    name = block.name
    if name.startswith("mcp__"):
        # mcp__databricks__foo -> mcp:foo
        parts = name.split("__")
        name = f"mcp:{parts[-1]}" if len(parts) > 2 else name
    inp = block.input or {}
    match name:
        case "Read" | "Write" | "Edit":
            path = inp.get("file_path", "")
            return f"{name}({path.split('/')[-1]})"
        case "Glob":
            return f"Glob({inp.get('pattern', '')})"
        case "Grep":
            return f"Grep({inp.get('pattern', '')[:20]})"
        case "Bash":
            cmd = inp.get("command", "")[:50]
            return f"Bash({cmd})"
        case "Skill":
            return f"Skill({inp.get('skill', '')})"
        case "Task":
            return f"Task({inp.get('subagent_type', '')})"
        case s if s.startswith("mcp:"):
            return s
        case _:
            return name


SKILL_SOURCE = Path.home() / ".claude" / "skills" / "databricks-apps"


def _setup_skill_env(base_dir: Path) -> Path:
    """Setup skill in parent dir, return workspace subdir as cwd."""
    skill_target = base_dir / ".claude" / "skills" / "databricks-apps"
    shutil.copytree(SKILL_SOURCE, skill_target)
    workspace = base_dir / "workspace"
    workspace.mkdir()
    return workspace


def _build_mcp_config(mcp_binary: str, mcp_args: list[str] | None) -> dict:
    project_root = Path(__file__).parent.parent
    mcp_manifest = validate_mcp_manifest(mcp_binary, project_root)
    command, args = build_mcp_command(mcp_binary, mcp_manifest, None, mcp_args)
    return {"type": "stdio", "command": command, "args": args, "env": {}}


AUTO_RESPONSE = "Continue with your best judgment. Use available tools to complete the task. I use Databricks"


@dataclass
class _TrialState:
    tool_calls: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    turns: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    triggered: bool = False
    interrupted: bool = False
    last_text: str | None = None
    last_turn_had_tools: bool = False  # track if last turn used tools


async def _process_response(
    client: ClaudeSDKClient,
    state: _TrialState,
    is_trigger: Callable[[str], bool],
    verbose: bool,
    log_prefix: str,
) -> bool:
    """Process response stream. Returns True if task done, False if waiting for user."""
    last_block_was_text = False
    async for message in client.receive_response():
        match message:
            case AssistantMessage():
                for block in message.content:
                    match block:
                        case TextBlock():
                            last_block_was_text = True
                            state.last_text = block.text
                            if verbose:
                                preview = block.text[:80].replace("\n", " ")
                                if len(block.text) > 80:
                                    preview += "..."
                                state.logs.append(f"{log_prefix}[text] {preview}")
                        case ToolUseBlock():
                            last_block_was_text = False
                            state.tool_calls.append(block.name)
                            if verbose:
                                state.logs.append(f"{log_prefix}[{_format_tool(block)}]")
                            if is_trigger(block.name) and not state.interrupted:
                                state.triggered = True
                                state.interrupted = True
                                await client.interrupt()
                                if verbose:
                                    state.logs.append(f"{log_prefix}[EARLY STOP]")
            case UserMessage():
                state.turns += 1
            case ResultMessage() as msg:
                state.turns = msg.num_turns
                state.cost_usd = msg.total_cost_usd or 0.0
                # if last block was text = asking user, not done
                task_done = not last_block_was_text or state.triggered
                if verbose:
                    status = "done" if task_done else "waiting"
                    state.logs.append(f"{log_prefix}[{status}] turns={state.turns} cost=${state.cost_usd:.4f}")
                return task_done
    return False


async def _run_trial(
    options: ClaudeAgentOptions,
    prompt: str,
    app_name: str,
    trigger_check: str,  # "mcp" or "Skill"
    verbose: bool,
    log_prefix: str,
) -> TrialResult:
    """Common trial runner with early stopping and auto-response."""
    state = _TrialState()

    def is_trigger(name: str) -> bool:
        return name.startswith("mcp") if trigger_check == "mcp" else name == "Skill"

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            ended = await _process_response(client, state, is_trigger, verbose, log_prefix)

            # auto-respond if agent asked question and didn't trigger/end
            while not ended and not state.triggered and state.turns < MAX_TURNS:
                if verbose:
                    state.logs.append(f"{log_prefix}[auto-respond]")
                await client.query(AUTO_RESPONSE)
                ended = await _process_response(client, state, is_trigger, verbose, log_prefix)

    except Exception as e:
        state.error = str(e)
        if verbose:
            state.logs.append(f"{log_prefix}[error] {str(e)[:100]}")

    if not state.triggered:
        state.triggered = any(is_trigger(tc) for tc in state.tool_calls)

    # log full last message if didn't trigger
    if not state.triggered and state.last_text and verbose:
        state.logs.append(f"{log_prefix}[FINAL MESSAGE] {state.last_text[:300]}")

    return TrialResult(
        app_name=app_name, triggered=state.triggered, tool_calls=state.tool_calls,
        turns=state.turns, cost_usd=state.cost_usd, error=state.error, logs=state.logs,
    )


# =============================================================================
# MCP TRIAL
# =============================================================================
async def run_trial_mcp(
    prompt: str, app_name: str, work_dir: Path,
    mcp_binary: str, mcp_args: list[str] | None,
    verbose: bool, log_prefix: str = "",
) -> TrialResult:
    options = ClaudeAgentOptions(
        model=MODEL,
        system_prompt={"type": "preset", "preset": "claude_code"},
        permission_mode="bypassPermissions",
        disallowed_tools=["NotebookEdit"],
        max_turns=MAX_TURNS,
        mcp_servers={"databricks": _build_mcp_config(mcp_binary, mcp_args)},  # type: ignore[arg-type]
        cwd=str(work_dir),
    )
    return await _run_trial(options, prompt, app_name, "mcp", verbose, log_prefix)


# =============================================================================
# SKILL TRIAL
# =============================================================================
async def run_trial_skill(
    prompt: str, app_name: str, work_dir: Path,
    verbose: bool, log_prefix: str = "",
) -> TrialResult:
    # workspace = _setup_skill_env(work_dir)
    workspace = work_dir
    options = ClaudeAgentOptions(
        model=MODEL,
        system_prompt={"type": "preset", "preset": "claude_code"},
        permission_mode="bypassPermissions",
        disallowed_tools=["NotebookEdit"],
        max_turns=MAX_TURNS,
        cwd=str(workspace),
        setting_sources=["user"],
    )
    return await _run_trial(options, prompt, app_name, "Skill", verbose, log_prefix)


async def run_single_prompt(
    app_name: str,
    prompt: str,
    mcp_binary: str,
    mcp_args: list[str] | None,
    verbose: bool,
) -> tuple[TrialResult, TrialResult]:
    """Run both MCP and Skill trials for a single prompt."""
    mcp_work_dir = Path(tempfile.mkdtemp(prefix=f"bench_mcp_{app_name}_"))
    skill_work_dir = Path(tempfile.mkdtemp(prefix=f"bench_skill_{app_name}_"))

    try:
        mcp_result = await run_trial_mcp(
            prompt, app_name, mcp_work_dir, mcp_binary, mcp_args, verbose, f"  {app_name[:15]:<15} MCP   "
        )
        skill_result = await run_trial_skill(
            prompt, app_name, skill_work_dir, verbose, f"  {app_name[:15]:<15} Skill "
        )

        # print buffered logs when job is done
        if verbose:
            for log in mcp_result.logs:
                print(log)
            for log in skill_result.logs:
                print(log)

        # print summary
        mcp_status = "✓" if mcp_result.triggered else "✗"
        skill_status = "✓" if skill_result.triggered else "✗"
        print(f"  {app_name}: MCP={mcp_status} Skill={skill_status}")

        return mcp_result, skill_result
    finally:
        shutil.rmtree(mcp_work_dir, ignore_errors=True)
        shutil.rmtree(skill_work_dir, ignore_errors=True)


async def run_benchmark(
    prompts: dict[str, str],
    mcp_binary: str,
    mcp_args: list[str] | None,
    verbose: bool,
    max_concurrency: int,
) -> tuple[BenchmarkResults, BenchmarkResults]:
    """Run benchmark for all prompts concurrently."""
    mcp_results = BenchmarkResults(approach="MCP")
    skill_results = BenchmarkResults(approach="Skill")

    sem = asyncio.Semaphore(max_concurrency)
    pbar = tqdm(total=len(prompts), desc="Benchmarking", unit="prompt")
    mcp_triggered = 0
    skill_triggered = 0

    async def run_with_sem(app_name: str, prompt: str) -> tuple[TrialResult, TrialResult]:
        nonlocal mcp_triggered, skill_triggered
        async with sem:
            result = await run_single_prompt(app_name, prompt, mcp_binary, mcp_args, verbose)
            mcp_triggered += 1 if result[0].triggered else 0
            skill_triggered += 1 if result[1].triggered else 0
            pbar.set_postfix(mcp=mcp_triggered, skill=skill_triggered)
            pbar.update(1)
            return result

    tasks = [run_with_sem(name, prompt) for name, prompt in prompts.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    pbar.close()

    errors = []
    for result in results:
        if isinstance(result, BaseException):
            errors.append(result)
            continue
        mcp_results.trials.append(result[0])
        skill_results.trials.append(result[1])

    if errors:
        print(f"\n{len(errors)} tasks failed:")
        for e in errors[:5]:
            print(f"  {type(e).__name__}: {e}")
        if len(errors) > 5:
            print(f"  ... and {len(errors) - 5} more")

    return mcp_results, skill_results


def print_summary(mcp: BenchmarkResults, skill: BenchmarkResults) -> None:
    """Print comparison summary."""
    print(f"\n{'=' * 60}")
    print("TRIGGER RATE COMPARISON")
    print(f"{'=' * 60}")
    print(f"{'Approach':<10} {'Triggered':<12} {'Rate':<10} {'Cost':<12} {'Errors':<10}")
    print(f"{'-' * 60}")

    mcp_triggered = sum(1 for t in mcp.trials if t.triggered)
    skill_triggered = sum(1 for t in skill.trials if t.triggered)

    print(f"{'MCP':<10} {mcp_triggered}/{len(mcp.trials):<10} {mcp.trigger_rate:>5.1f}%{'':>4} ${mcp.total_cost:<10.4f} {mcp.error_count:<10}")
    print(f"{'Skill':<10} {skill_triggered}/{len(skill.trials):<10} {skill.trigger_rate:>5.1f}%{'':>4} ${skill.total_cost:<10.4f} {skill.error_count:<10}")

    print(f"\n{'─' * 60}")
    print("Tool distribution (MCP):")
    for tool, count in list(mcp.tool_distribution().items())[:10]:
        print(f"  {tool}: {count}")

    print(f"\n{'─' * 60}")
    print("Tool distribution (Skill):")
    for tool, count in list(skill.tool_distribution().items())[:10]:
        print(f"  {tool}: {count}")


def main(
    mcp_binary: str,
    mcp_args: list[str] | None = None,
    prompt_set: str = "test",
    limit: int | None = None,
    verbose: bool = False,
    max_concurrency: int = 5,
) -> None:
    """Benchmark trigger rate: Skill vs MCP context injection.

    Runs both approaches on the same prompts and compares trigger rates.

    Args:
        mcp_binary: Path to MCP binary (required)
        mcp_args: Optional MCP server args (e.g. '["experimental", "apps-mcp"]')
        prompt_set: Prompt set to use ("databricks", "databricks_v2", "test")
        limit: Limit number of prompts (for quick testing)
        verbose: Show detailed tool calls during execution
        max_concurrency: Max prompts to process concurrently (default: 4)
    """
    prompts = get_prompts(prompt_set)
    if limit:
        prompts = dict(list(prompts.items())[:limit])

    print(f"\n{'=' * 60}")
    print("TRIGGER RATE BENCHMARK (early stopping)")
    print(f"{'=' * 60}")
    print(f"Prompt set: {prompt_set} ({len(prompts)} prompts)")
    print(f"Max turns per trial: {MAX_TURNS}")
    print(f"Max concurrency: {max_concurrency}")
    print(f"MCP binary: {mcp_binary}")
    if verbose:
        print("Verbose: ON")

    mcp_results, skill_results = asyncio.run(run_benchmark(prompts, mcp_binary, mcp_args, verbose, max_concurrency))
    print_summary(mcp_results, skill_results)


if __name__ == "__main__":
    fire.Fire(main)
