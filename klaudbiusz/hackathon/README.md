# Self-Improving Skill System

A three-agent system that evolves a Claude Code skill through iterative feedback loops.

## Concept

```
┌─────────────────────────────────────────────────────────────────┐
│                         EVOLUTION LOOP                          │
│                                                                 │
│   ┌──────────┐      ┌──────────┐      ┌──────────┐             │
│   │ BUILDER  │ ───► │  GRADER  │ ───► │ ENGINEER │ ──┐         │
│   │          │      │          │      │          │   │         │
│   │ builds   │      │ analyzes │      │ improves │   │         │
│   │ apps     │      │ quality  │      │ skill    │   │         │
│   └──────────┘      └──────────┘      └──────────┘   │         │
│        ▲                                             │         │
│        └─────────────────────────────────────────────┘         │
│                      next iteration                             │
└─────────────────────────────────────────────────────────────────┘
```

The system starts with a simple skill for building web apps. Through multiple iterations:

1. **Builder** creates apps using the skill
2. **Grader** evaluates the apps and identifies skill weaknesses
3. **Engineer** improves the skill based on feedback

Each iteration produces better apps as the skill evolves.

## Architecture

### Three Agents, Three Skills

Each agent uses a dedicated Claude Code skill:

| Agent | Skill | Purpose |
|-------|-------|---------|
| Builder | `webapp-creation` | Build TypeScript web apps from prompts |
| Grader | `webapp-grading` | Analyze apps, trajectory, take screenshots (Playwright) |
| Engineer | `skill-improver` | Improve webapp-creation based on feedback |

### Information Flow

```
Builder                    Grader                     Engineer
   │                          │                          │
   │ creates app              │                          │
   │ + trajectory.jsonl       │                          │
   │                          │                          │
   └─────────────────────────►│                          │
                              │ reads trajectory         │
                              │ reads source code        │
                              │ takes screenshot         │
                              │ outputs feedback.json    │
                              │                          │
                              └─────────────────────────►│
                                                         │ reads feedback
                                                         │ modifies skill
                                                         │
                                                         ▼
                                               improved skill for
                                               next iteration
```

**Key design**: Engineer only sees Grader's structured feedback, not raw trajectory. Grader is responsible for digesting trajectory + screenshots into actionable insights.

## The Evolving Skill

The `webapp-creation` skill is what gets improved. It contains:

```
skills/webapp-creation/
├── SKILL.md              # workflow instructions
├── template/
│   ├── index.html        # HTML shell
│   ├── styles.css        # base styles
│   └── app.ts            # TypeScript starter with helpers
├── scripts/
│   └── validate          # type-checking script
└── reference/
    └── patterns.md       # TypeScript patterns guide
```

The `webapp-grading` skill includes a Playwright-based screenshot script:

```
skills/webapp-grading/
├── SKILL.md              # grading workflow
└── scripts/
    └── screenshot        # captures app UI via Playwright
```

Engineer can modify any of these files based on grader feedback:
- Unclear instructions? → improve SKILL.md
- Type errors? → improve template/app.ts
- Missing patterns? → add to reference/patterns.md
- Validation gaps? → update scripts/validate

## Feedback Structure

Grader outputs structured JSON that guides Engineer:

```json
{
  "app_name": "todo-app",
  "score": 75,
  "type_safe": true,
  "works": true,
  "issues": [
    {
      "severity": "high",
      "category": "types",
      "description": "localStorage returns string|null, not parsed object"
    }
  ],
  "successes": [
    "Clean DOM helper usage",
    "Proper event typing"
  ],
  "skill_suggestions": [
    {
      "file": "reference/patterns.md",
      "suggestion": "Add localStorage typing example with JSON.parse"
    }
  ],
  "trajectory_insights": [
    "Builder took 3 attempts to get localStorage types right"
  ]
}
```

## Usage

```bash
cd klaudbiusz/hackathon

# run with defaults (3 iterations, 3 apps each)
uv run python main.py

# customize
uv run python main.py --num_iterations=5 --prompts_per_iteration=2

# use different model
uv run python main.py --model=claude-sonnet-4-5-20250929

# verbose mode - see tool calls, turns, costs
uv run python main.py --verbose
```

## Output Structure

Each run creates:

```
runs/run-20241210_143052/
├── config.json                    # run configuration
├── summary.json                   # metrics across iterations
├── working-skill/                 # current skill being evolved
│   └── webapp-creation/           # (modified in place by engineer)
├── skill-versions/                # immutable snapshots
│   ├── v0/                        # initial skill snapshot
│   ├── v1/                        # after iteration 1
│   └── v2/                        # after iteration 2
└── iterations/
    ├── iter-0/
    │   ├── apps/
    │   │   ├── todo-app/
    │   │   │   ├── index.html
    │   │   │   ├── app.ts
    │   │   │   ├── trajectory.jsonl
    │   │   │   └── screenshot.png
    │   │   └── counter-app/
    │   │       └── ...
    │   └── feedback.json
    ├── iter-1/
    │   └── ...
    └── iter-2/
        └── ...
```

The original `skills/webapp-creation` is never modified - all evolution happens in the run directory.

## Prompts

Default prompts (from `prompts.py`):

- **todo-app**: Todo list with add, complete, delete + localStorage
- **counter-app**: Increment, decrement, reset buttons
- **color-picker**: RGB/HEX/HSL with sliders
- **timer-app**: Countdown with start, pause, reset
- **quote-generator**: Random quotes with button

## How It Works

### Iteration 0 (baseline)

1. Copy `skills/webapp-creation` to `working-skill/` and snapshot as `v0`
2. Builder uses working skill to create 3 apps (with trajectory capture)
3. Grader analyzes each app:
   - Reads source code
   - Reads trajectory to understand builder's process
   - Takes screenshot via Playwright
   - Outputs structured feedback
4. Engineer reads aggregated feedback, modifies working skill
5. Snapshot working skill as `v1`

### Iteration 1 (improved)

1. Builder uses modified working skill (hopefully clearer instructions)
2. Should produce better apps (fewer type errors, etc.)
3. Grader identifies remaining issues
4. Engineer makes further improvements to working skill
5. Snapshot as `v2`

### Final Iteration

- No engineering phase (just build + grade)
- Final metrics show improvement over baseline
- Compare `skill-versions/v0` vs final version to see evolution

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Orchestrator + CLI entry point |
| `config.py` | EvolutionConfig dataclass |
| `agents/builder.py` | Runs builder with trajectory capture |
| `agents/grader.py` | Runs grader, extracts JSON feedback |
| `agents/engineer.py` | Runs engineer to improve skill |
| `models/feedback.py` | FeedbackReport dataclass |

## Design Decisions

### Why skills instead of direct prompts?

Skills provide structure:
- Template gives consistent starting point
- Scripts enable validation
- Reference docs accumulate knowledge
- Progressive disclosure (SKILL.md → reference → examples)

### Why grader reads trajectory?

Trajectory reveals *process*, not just *result*:
- Where did builder struggle?
- What instructions caused confusion?
- How many retries for each part?

This informs better skill improvements than just looking at final code.

### Why engineer only sees feedback?

Abstraction layers:
- Grader is the "expert" that interprets raw data
- Engineer focuses on actionable improvements
- Prevents engineer from getting lost in trajectory details

### Why TypeScript?

Type safety enables:
- Automated validation via `scripts/validate`
- Clear success/failure signal for grader
- Pattern enforcement through interfaces

## Extending

### Add new prompts

Edit `prompts.py`:

```python
PROMPTS = {
    # existing...
    "calculator": "Build a calculator with basic operations...",
}
```

### Modify grading criteria

Edit `skills/webapp-grading/SKILL.md`:
- Change scoring weights
- Add new categories
- Modify output format

### Change what engineer can modify

Edit `skills/skill-improver/SKILL.md`:
- Restrict to certain files
- Add new improvement strategies
- Change priority rules
