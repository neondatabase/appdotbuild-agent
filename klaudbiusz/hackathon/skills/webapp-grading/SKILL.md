---
name: webapp-grading
description: Grade full-stack web applications by analyzing code, trajectory, and screenshots. Provides structured feedback for skill improvement.
---

You grade full-stack web apps (React Admin + FastAPI) and provide structured feedback.

## Input

You will receive:
- App directory path with source files (backend/, frontend/, Dockerfile)
- Trajectory file path (trajectory.jsonl) showing how the app was built

## Workflow

1. **Read source files** - Examine backend/ (models.py, schemas.py, main.py) and frontend/src/ (App.tsx, resources/)
2. **Read trajectory** - Understand builder's process, struggles, decisions
3. **Take screenshot** - Run the screenshot command, then read the image
4. **Analyze quality** - Backend types, frontend components, API design, UI
5. **Output JSON feedback** - Structured report for skill improvement

## Screenshot

Use edda-screenshot to capture the app's UI (requires Dockerfile in app directory):
```bash
/Users/arseni.kravchenko/dev/agent/edda/target/release/edda-screenshot app \
  --app-source /path/to/app \
  --port 80 \
  --wait-time 5000 \
  --output /path/to/app
```

This creates `screenshot.png` in the output directory. Then read it to see how the app renders.

## Trajectory Analysis

The trajectory.jsonl contains the builder's conversation. Look for:
- Where did the builder struggle or retry?
- What instructions were unclear?
- What patterns were used incorrectly?
- How many turns did it take?

## Grading Criteria

Score 0-10 for each dimension:

### 1. Code Quality (0-10)
- Clean structure, proper patterns
- Backend: SQLAlchemy models, Pydantic schemas, typed endpoints
- Frontend: React Admin resources, TypeScript types
- Error handling, edge cases

### 2. UI/UX (0-10)
- Visual appearance and layout
- React Admin components used correctly
- Usability and interaction design
- Consistency and polish

### 3. Prompt Relevancy (0-10)
- Does the app fulfill the original request?
- Are all requested features implemented?
- Does it match user expectations?

### 4. Agent Efficiency (0-10)
- How many turns did the builder take?
- Did it struggle or retry excessively?
- Was the approach direct or roundabout?
- Resource usage (fewer turns = better)

**Total score**: Average of all four dimensions (0-10)

## Output Format

Output ONLY valid JSON (no markdown, no explanation):

```json
{
  "app_name": "task-manager",
  "scores": {
    "code_quality": 7,
    "ui_ux": 8,
    "prompt_relevancy": 9,
    "agent_efficiency": 6
  },
  "score": 7.5,
  "type_safe": true,
  "works": true,
  "issues": [
    {
      "severity": "high",
      "category": "types",
      "description": "Missing Pydantic schema for Task update"
    },
    {
      "severity": "medium",
      "category": "skill",
      "description": "SKILL.md unclear about relationship typing"
    }
  ],
  "successes": [
    "Clean SQLAlchemy model structure",
    "Proper React Admin resource setup"
  ],
  "skill_suggestions": [
    {
      "file": "reference/patterns.md",
      "suggestion": "Add example for nullable foreign keys"
    },
    {
      "file": "template/backend/schemas.py",
      "suggestion": "Include UpdateSchema example with Optional fields"
    }
  ],
  "trajectory_insights": [
    "Builder struggled with foreign key types - needed 3 attempts",
    "React Admin resources were done correctly on first try"
  ]
}
```

## Categories

- `types` - Python/TypeScript type errors or missing types
- `logic` - Broken functionality, bugs
- `ui` - Visual issues, bad UX
- `skill` - Issues caused by unclear skill instructions
- `efficiency` - Agent took too many turns or retried excessively

## Severity

- `high` - Blocks functionality or causes errors
- `medium` - Quality issue but app works
- `low` - Minor improvement suggestion

## Files to Check

Backend:
- `backend/models.py` - SQLAlchemy models
- `backend/schemas.py` - Pydantic schemas
- `backend/main.py` - FastAPI endpoints

Frontend:
- `frontend/src/App.tsx` - Resource registration
- `frontend/src/resources/*.tsx` - CRUD components
- `frontend/src/dataProvider.ts` - API integration
