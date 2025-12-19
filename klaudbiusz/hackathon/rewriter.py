"""Prompt rewriting for variation in each iteration."""

import anthropic


REWRITE_SYSTEM = """You rewrite web app prompts to add minor variations while keeping the core idea.

Rules:
- Keep the same app type and core functionality
- Add, remove, or modify 1-2 minor features
- Add ONE UI style variation (pick randomly from: dark theme, emoji icons, card-based layout, minimal/clean style, colorful accents, rounded corners, gradient backgrounds)
- Change wording/phrasing
- Keep similar length (2-3 sentences max)
- Output ONLY the rewritten prompt, nothing else

Examples of valid variations:
- "todo app with tasks" -> "todo app with tasks and due dates. Use a dark theme with card-based layout."
- "bookmark manager with tags" -> "bookmark manager with folders. Use emoji icons and a minimal clean style."
- "guest book with names" -> "guest book with names and optional email. Use colorful accents and rounded corners."
"""


async def rewrite_prompt(prompt: str, model: str = "claude-sonnet-4-5-20250929") -> str:
    """Rewrite a prompt with minor variations.

    Returns the rewritten prompt, or original if rewrite fails.
    """
    client = anthropic.AsyncAnthropic()

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=256,
            system=REWRITE_SYSTEM,
            messages=[{"role": "user", "content": f"Rewrite this prompt:\n\n{prompt}"}],
        )

        rewritten = response.content[0].text.strip()
        # sanity check - should be similar length
        if len(rewritten) < 20 or len(rewritten) > len(prompt) * 3:
            return prompt
        return rewritten

    except Exception:
        return prompt


async def rewrite_prompts(prompts: dict[str, str], model: str = "claude-sonnet-4-5-20250929") -> dict[str, str]:
    """Rewrite all prompts with variations.

    Returns dict with same keys, rewritten values.
    """
    import asyncio

    async def rewrite_one(name: str, prompt: str) -> tuple[str, str]:
        rewritten = await rewrite_prompt(prompt, model)
        return name, rewritten

    tasks = [rewrite_one(name, prompt) for name, prompt in prompts.items()]
    results = await asyncio.gather(*tasks)

    return dict(results)
