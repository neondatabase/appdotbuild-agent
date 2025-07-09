# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

**Refer to `PROJECT_GUIDELINES.md` for detailed project information (Overview, Structure, Workflow, Code Style, Patterns, User Lessons).**

## Common Tasks and Examples

*[Add examples of common development tasks, like adding a new agent, extending the API, etc.]*

## Known Issues and Workarounds

### Function Calling Model Compatibility

Not all Ollama models support function calling properly, which is required for the agent's FSM tools to work correctly. Models that don't support function calling will cause endless refinement loops.

**Compatible Models (tested):**
- `llama3.3:latest` ✅
- `devstral:latest` ✅

**Incompatible Models:**
- `qwen2.5-coder:32b` ❌ (returns function calls as text)
- `gemma3:27b` ❌ (explicitly doesn't support tools)

**Symptoms of incompatible models:**
- Agent gets stuck in endless refinement loops
- Generate command hits the 5-attempt limit and fails
- Models return function calls as plain text instead of using tool_calls format

**Solution:** Use a function calling compatible model in `.env`:
```bash
LLM_BEST_CODING_MODEL=llama3.3:latest
LLM_UNIVERSAL_MODEL=llama3.3:latest
```

## Contributing Guidelines

*[Add any specific guidelines for contributing to the project]*
