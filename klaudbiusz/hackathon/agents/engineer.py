import json
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    UserMessage,
    query,
)


@dataclass
class EngineerResult:
    success: bool
    plan: str  # free form plan text


async def run_engineer(
    feedback_reports: list[dict],
    history: list[dict],
    iteration: int,
    webapp_creation_skill: Path,
    improver_skill: Path,
    run_dir: Path,
    model: str,
    max_turns: int,
    verbose: bool = False,
) -> EngineerResult:
    """Improve webapp-creation skill based on grader feedback and history.

    Returns EngineerResult with plan summary and actions taken.
    """
    # set up .claude/skills with skill-improver for this agent
    claude_skills = run_dir / ".claude" / "skills"
    claude_skills.mkdir(parents=True, exist_ok=True)
    skill_link = claude_skills / "skill-improver"
    if not skill_link.exists():
        skill_link.symlink_to(improver_skill.resolve())
        if verbose:
            print(f"    [skill] skill-improver -> {improver_skill}")
            print(f"    [target] {webapp_creation_skill}")

    feedback_json = json.dumps(feedback_reports, indent=2)
    history_json = json.dumps(history, indent=2) if history else "[]"

    user_prompt = f"""Improve the webapp-creation skill based on grading feedback.

Iteration: {iteration}
Skill to improve: {webapp_creation_skill}

## History of Past Improvements

Each entry shows what was tried and whether it helped (score delta):
{history_json}

Use this to avoid repeating ineffective changes and build on what worked.

## Current Iteration Feedback

Feedback from {len(feedback_reports)} app builds:
{feedback_json}

## Instructions

Use the skill-improver skill. You MUST:
1. First write a plan to `plan.md` in current directory with:
   - Summary (one line)
   - Actions you will take (numbered list)
2. Then execute the plan by modifying the skill files

Focus on patterns appearing in multiple apps. Check history to avoid repeating failed approaches.
"""

    options = ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code"},
        permission_mode="bypassPermissions",
        allowed_tools=["Skill", "Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        max_turns=max_turns,
        model=model,
        cwd=str(run_dir),
        setting_sources=["project"],
    )

    turn_count = 0
    try:
        async for msg in query(prompt=user_prompt, options=options):
            if verbose:
                match msg:
                    case AssistantMessage():
                        for block in msg.content:
                            match block:
                                case TextBlock():
                                    preview = block.text[:100].replace("\n", " ")
                                    if len(block.text) > 100:
                                        preview += "..."
                                    print(f"      [text] {preview}")
                                case ToolUseBlock():
                                    tool_info = block.name
                                    if block.name == "Bash" and isinstance(block.input, dict):
                                        cmd = block.input.get("command", "")[:50]
                                        tool_info = f"Bash: {cmd}"
                                    elif block.name in ("Read", "Write", "Edit") and isinstance(block.input, dict):
                                        path = block.input.get("file_path", "")
                                        tool_info = f"{block.name}: {path.split('/')[-1]}"
                                    print(f"      [{tool_info}]")
                    case UserMessage():
                        turn_count += 1
                        print(f"      [turn {turn_count}]")
                    case ResultMessage():
                        print(f"      [done] turns={msg.num_turns} cost=${msg.total_cost_usd:.4f}")

        # read plan.md if it exists
        plan_path = run_dir / "plan.md"
        plan = "No plan written"
        if plan_path.exists():
            plan = plan_path.read_text().strip()

        return EngineerResult(success=True, plan=plan)

    except Exception as e:
        if verbose:
            print(f"      [error] {e}")
        print(f"Engineer error: {e}")
        return EngineerResult(success=False, plan=f"Error: {e}")
