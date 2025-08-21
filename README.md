<div align="center">
  <img src="logo.png" alt="app.build logo" width="150">
</div>

# app.build (agent)

**app.build** is an open-source AI agent for generating production-ready applications with testing, linting and deployment setup from a single prompt.

## What it builds

We're currently supporting the following application types:

### tRPC CRUD Web Applications

- **Full-stack web apps** with Bun, React, Vite, Fastify, tRPC and Drizzle;
- **Automatic validation** with ESLint, TypeScript, and runtime verification;
- **Applications tested** ahead of generation with smoke tests using Playwright

### Laravel Web Applications (Alpha Version)

- **Full-stack web apps** with Laravel, React, TypeScript, Tailwind CSS, and Inertia.js;
- **Modern Laravel 12** with PHP 8+ features and strict typing;
- **Built-in authentication** with Laravel Breeze providing complete user registration, login, and profile management;
- **Production-ready features** including validation, testing infrastructure, and code style enforcement;
- **AI-powered development** that creates complete applications including models, migrations, controllers, and React components from a single prompt;

### Data-oriented Applications

- **Data apps** with Python + NiceGUI + SQLModel stack - perfect for dashboards and data visualization;
- **Automatic validation** using pytest, ruff, pyright, and runtime verification;
- **Additional packages management** with uv;

All applications support:
- **[Neon Postgres DB](https://get.neon.com/ab5)** provisioned instantly via API
- **GitHub repository** with complete source code
- **CI/CD and deployment** via the [app.build platform](https://github.com/appdotbuild/platform).

New application types are work in progress, stay tuned for updates!

## Try it

### Via the [managed service](https://app.build)

### Locally
Local usage and development instructions are available in [CONTRIBUTING.md](CONTRIBUTING.md).

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

## Repository structure

This is the **agent** repository containing the core code generation engine and runtime environment. The CLI and platform code are available in the [platform repository](https://github.com/appdotbuild/platform).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and contribution guidelines.

---

Built to showcase agent-native infrastructure patterns. Fork it, remix it, use it as a reference for your own projects.
