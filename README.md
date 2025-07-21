<div align="center">
  <img src="logo.png" alt="app.build logo" width="150">
</div>

# app.build (agent)

**app.build** is an open-source AI agent for generating production-ready full-stack applications from a single prompt.

## What it builds

We're currently supporting the following application types:

### tRPC CRUD Web Applications

- **Full-stack web apps** with Bun, React, Vite, Fastify, tRPC and Drizzle;
- **Automatic validation** with ESLint, TypeScript, and runtime verification;
- **Applications tested** ahead of generation with smoke tests using Playwright

### Laravel Web Applications (Alpha Version)

- **Full-stack web apps** with Laravel, React, TypeScript, Tailwind CSS, and Inertia.js;
- **Modern Laravel 12** with PHP 8+ features and strict typing;
- Designed to become production-ready soon with authentication, validation, code style enforcement and testing infrastructure;

### Data-oriented Applications

- **Data apps** with Python + NiceGUI + SQLModel stack - perfect for dashboards and data visualization;
- **Automatic validation** using pytest, ruff, pyright, and runtime verification;
- **Additional packages management** with uv;

All applications support:
- **Neon Postgres database** provisioned instantly via API
- **GitHub repository** with complete source code
- **CI/CD and deployment** via the [app.build platform](https://github.com/appdotbuild/platform).

New application types are work in progress, stay tuned for updates!

## Try it

### Via the [managed service](https://app.build)

```bash
# for tRPC CRUD apps
npx @app.build/cli

for Python/NiceGUI apps
npx @app.build/cli --template=python
```

### Locally
Local usage and development instructions are available in [CONTRIBUTING.md](CONTRIBUTING.md).

### Local Models with Ollama (expreimental)

Want to run everything locally without API keys? We  added experimental support [Ollama](https://ollama.ai) for local model inference. Set up Ollama, pull your preferred models, and run the agent completely offline. See [PROJECT_GUIDELINES.md](PROJECT_GUIDELINES.md) for detailed setup instructions and recommended models.

We are open for you contributions in better supporting local models. Feel free to send you PRs!

## Architecture

This agent doesn't generate entire applications at once. Instead, it breaks down app creation into small, well-scoped tasks that run in isolated sandboxes:

1. **Database schema generation** - Creates typed database models
2. **API handler logic** - Builds validated Fastify routes
3. **Frontend components** - Generates React UI with proper typing

Each task is validated independently using ESLint, TypeScript compilation, test execution, and runtime logs before being accepted.

More details on the architecture can be found in the [blog on our design decisions](https://www.app.build/blog/design-decisions).

## Repository structure

This is the **agent** repository containing the core code generation engine and runtime environment. The CLI and platform code are available in the [platform repository](https://github.com/appdotbuild/platform).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and contribution guidelines.

---

Built to showcase agent-native infrastructure patterns. Fork it, remix it, use it as a reference for your own projects.
