"""LLM-based generation utilities for app names and commit messages."""

import logging
import re

from llm.utils import AsyncLLM
from llm.common import Message, TextRaw

logger = logging.getLogger(__name__)


async def generate_app_name(prompt: str, llm_client: AsyncLLM) -> str:
    """Generate a GitHub repository name from the application description"""
    try:
        logger.info(f"Generating app name from prompt: {prompt[:50]}...")

        messages = [
            Message(
                role="user",
                content=[
                    TextRaw(f"""Based on this application description, generate a short, concise name suitable for use as a GitHub repository name.
The name should be lowercase with words separated by hyphens (kebab-case) and should not include any special characters.
Application description: "{prompt}"
Return ONLY the name, nothing else.""")
                ],
            )
        ]

        completion = await llm_client.completion(
            messages=messages, max_tokens=50, temperature=0.7
        )

        generated_name = ""
        for block in completion.content:
            if isinstance(block, TextRaw):
                name = block.text.strip().strip("\"'").lower()
                name = re.sub(
                    r"[^a-z0-9\-]", "-", name.replace(" ", "-").replace("_", "-")
                )
                name = re.sub(r"-+", "-", name)
                name = name.strip("-")
                generated_name = name
                break

        if not generated_name:
            logger.warning("Failed to generate app name, using default")
            return "generated-application"

        logger.info(f"Generated app name: {generated_name}")
        return generated_name
    except Exception as e:
        logger.exception(f"Error generating app name: {e}")
        return "generated-application"


async def generate_commit_message(user_request: str, llm_client: AsyncLLM) -> str:
    """Generate a Git commit message from the application description and user input"""
    try:
        logger.info(f"Generating commit message from prompt: {user_request[:50]}...")

        messages = [
            Message(
                role="user",
                content=[
                    TextRaw(f"""Based on this user request,
generate a concise Git commit message that follows best practices.
The message should be clear, descriptive, and follow conventional commit format.
User request: "{user_request}"
Return ONLY the commit message, nothing else.""")
                ],
            )
        ]
        completion = await llm_client.completion(
            messages=messages, max_tokens=100, temperature=0.7
        )

        commit_message = ""
        for block in completion.content:
            if isinstance(block, TextRaw):
                message = block.text.strip().strip("\"'")
                commit_message = message
                break

        if not commit_message:
            logger.warning("Failed to generate commit message, using default")
            return "Initial commit"

        logger.info(f"Generated commit message: {commit_message}")
        return commit_message
    except Exception as e:
        logger.exception(f"Error generating commit message: {e}")
        return "Initial commit"
