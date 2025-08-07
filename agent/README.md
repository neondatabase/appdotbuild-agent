# Full-stack codegen

Generates full stack apps using trpc + shadcn components.
See [CONTRIBUTING.md](https://github.com/appdotbuild/agent/blob/main/CONTRIBUTING.md) for more details.

## Using Non-Default (Open Source) LLMs

Configure LLM providers using `backend:model` format in environment variables:

### Local Models
```bash
# Ollama (requires ollama running locally)
LLM_BEST_CODING_MODEL=ollama:devstral
LLM_ULTRA_FAST_MODEL=ollama:phi4

# LMStudio with custom host
LLM_UNIVERSAL_MODEL=lmstudio:http://localhost:1234
# Or using default port (1234)
LLM_BEST_CODING_MODEL=lmstudio:local-model
```

### OpenRouter
```bash
# OpenRouter (requires API key)
OPENROUTER_API_KEY=your-api-key
LLM_BEST_CODING_MODEL=openrouter:deepseek/deepseek-coder
LLM_UNIVERSAL_MODEL=openrouter:openai/gpt-4o-mini
```

### Model Categories
- `LLM_BEST_CODING_MODEL` - High quality coding tasks (default: Claude Sonnet 4)
- `LLM_UNIVERSAL_MODEL` - General purpose tasks (default: Gemini Flash 2.5)
- `LLM_ULTRA_FAST_MODEL` - Quick tasks (commit messages, etc., default: Gemini Flash Lite 2.5)
- `LLM_VISION_MODEL` - Image/UI analysis tasks (default: Gemini Flash Lite 2.5)
