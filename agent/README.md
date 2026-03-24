# Development Environment

## Basic Usage

1) Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and [dagger](https://dagger.io)
2) Make sure you have `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` env vars available.
3) Run the commands

### Commands t

All the commands are run using `uv` from `agent` directory.

```
uv run test  # run all tests
uv run test_e2e  # only run e2e test
uv run lint   # lint and autofix the code
uv run update_cache  # update the LLM cache, required for new prompts or generation logic changes
uv run generate "my app description" # generate an app from scratch using full pipeline, similar to e2e test
uv run interactive  # a naive debug client working with local server
```

### App templates

We support three app templates:
- **trpc**: Full-stack web app with Bun, React, Vite, Fastify, tRPC and Drizzle
- **python**: Data-oriented app with Python, NiceGUI, and SQLModel
- **laravel**: Full-stack web app with Laravel, React, TypeScript, Tailwind CSS, and Inertia.js (early version)

You can specify the template when generating an app, e.g.:

```bash
uv run generate "make a dashboard showing my current stock portfolio value using up to date prices from yfinance" --template_id "nicegui_agent"
```
or

```bash
uv run generate "make a presentation-like website with multiple pages with content and next buttons on each. last page mush show a counter that increments each time this presentation has been shown" --template_id "laravel_agent"
```


## Architecture

This agent doesn't generate entire applications at once. Instead, it breaks down app creation into small, well-scoped tasks that run in isolated sandboxes:

### tRPC Applications
1. **Database schema generation** - Creates typed database models
2. **API handler logic** - Builds validated Fastify routes
3. **Frontend components** - Generates React UI with proper typing

### Laravel Applications
1. **Database migrations & models** - Creates Laravel migrations with proper syntax and Eloquent models with PHPDoc annotations
2. **Controllers & routes** - Builds RESTful controllers with Form Request validation
3. **Inertia.js pages** - Generates React components with TypeScript interfaces
4. **Validation & testing** - Runs PHPStan, architecture tests, and feature tests

Each task is validated independently using language-specific tools (ESLint/TypeScript for JS, PHPStan for PHP), test execution, and runtime logs before being accepted.

More details on the architecture can be found in the [blog on our design decisions](https://www.app.build/blog/design-decisions).

## Custom LLM Configuration

Override default models using `backend:model` format:

```bash
# Local (Ollama and LMStudio supported)
LLM_BEST_CODING_MODEL=ollama:devstral
LLM_UNIVERSAL_MODEL=lmstudio:[host] # just lmstudio: works too

# Cloud providers
OPENROUTER_API_KEY=your-key
LLM_BEST_CODING_MODEL=openrouter:deepseek/deepseek-coder
```
Among cloud providers, we support Gemini, Anthropic, OpenAI, and OpenRouter.

**Defaults**:

```bash
LLM_BEST_CODING_MODEL=anthropic:claude-sonnet-4-20250514   # code generation
LLM_UNIVERSAL_MODEL=gemini:gemini-2.5-flash-preview-05-20  # universal model, chat with user
LLM_ULTRA_FAST_MODEL=gemini:gemini-2.5-flash-lite-preview-06-17  # commit generation etc.
LLM_VISION_MODEL=gemini:gemini-2.5-flash-lite-preview-06-17  # vision model for UI validation
```
