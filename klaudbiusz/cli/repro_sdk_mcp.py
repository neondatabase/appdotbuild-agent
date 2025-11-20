import asyncio
import os

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, create_sdk_mcp_server, tool


@tool(
    "test_tool",
    description="A test tool",
    input_schema={
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
    },
)
async def test_tool(args: dict) -> dict:
    return {"content": [{"type": "text", "text": "ok"}]}


# create SDK-style MCP server with one tool
mcp_server = create_sdk_mcp_server("test", tools=[test_tool])


async def test():
    # configure databricks endpoint
    os.environ["ANTHROPIC_MODEL"] = "databricks-claude-sonnet-4-5"
    os.environ["ANTHROPIC_BASE_URL"] = f"https://{os.getenv('DATABRICKS_HOST')}/serving-endpoints/anthropic"
    os.environ["ANTHROPIC_AUTH_TOKEN"] = os.getenv("DATABRICKS_TOKEN", "")
    os.environ["ANTHROPIC_API_KEY"] = ""

    # configure MCP server
    options = ClaudeAgentOptions(
        system_prompt="test",
        permission_mode="bypassPermissions",
        max_turns=1,
        mcp_servers={"test": mcp_server},
    )

    print("Sending request to Databricks with MCP tools...")
    async with ClaudeSDKClient(options=options) as client:
        await client.query("Use mcp__test__test_tool with message='hello'")

        async for msg in client.receive_response():
            print(f"{type(msg).__name__}: {str(msg.content)[:200] if hasattr(msg, 'content') else ''}")


if __name__ == "__main__":
    asyncio.run(test())
