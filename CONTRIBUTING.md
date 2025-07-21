# Development Environment

## Basic Usage

1) Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and [dagger](https://dagger.io)
2) Make sure you have `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` env vars available.
3) Run the commands

### Commands

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


### Testing with debug client on prod servers

1. Make sure you have the `uv` installed
2. `uv run interactive --host yourhostname --port 80` (or change the host if needed);
3. In the client, prompt for your app.
4. Waste some time, get some tea.
5. After getting a large output, use `/apply`
6. There will be a new dir in the output, open new tab and `cd` there.
7. `docker compose up`. Optionally you can use your other DB: set env variable `DATABASE_URL=<your_db_url>`; otherwise we use postgres in docker.
8. Go to `localhost:80`


### VCR Testing

We use VCR for testing LLM calls. VCR records LLM completions and saves them to a cache file, allowing us to replay them in tests. This is useful for testing LLM interactions without making real API calls.

- **Record mode**: Makes real API calls, saves responses to cache
- **Replay mode**: Uses only cached responses
- **LRU mode**: Tries using cached responses, but can call APIs too.
- **Off mode**: No caching, direct API calls

Default usage (to run tests with cached responses):
```
LLM_VCR_CACHE_MODE=replay uv run pytest .
```

If you want to record new responses, use:

```
LLM_VCR_CACHE_MODE=record uv run pytest .
```
New responses should be recorded in case of prompt changes or other significant changes in the pipeline (e.g. template modification, adding new steps etc.). VCR cache is stored in ./agent/llm/llm_cache.json by default, and new version should be committed to the repository.
