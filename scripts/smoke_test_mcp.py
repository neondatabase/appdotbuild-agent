#!/usr/bin/env python3
"""
Smoke test for dabgent_mcp binary.
Verifies the MCP server starts, responds to protocol messages, and lists tools.
"""

import json
import subprocess
import sys
from pathlib import Path


def send_request(process: subprocess.Popen, request: dict) -> dict:
    """send JSON-RPC request and read response"""
    request_line = json.dumps(request) + "\n"
    process.stdin.write(request_line.encode())
    process.stdin.flush()

    response_line = process.stdout.readline().decode().strip()
    if not response_line:
        raise RuntimeError("no response from MCP server")

    return json.loads(response_line)


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path-to-dabgent_mcp-binary>")
        sys.exit(1)

    binary_path = Path(sys.argv[1])
    if not binary_path.exists():
        print(f"Error: Binary not found at {binary_path}")
        sys.exit(1)

    print(f"Starting MCP server: {binary_path}")

    # start the MCP server
    process = subprocess.Popen(
        [str(binary_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # 1. initialize request
        print("\n1. Sending initialize request...")
        init_response = send_request(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke-test", "version": "1.0.0"},
                },
            },
        )

        if "result" not in init_response:
            print(f"❌ Initialize failed: {init_response}")
            sys.exit(1)

        server_info = init_response["result"]
        print(f"✓ Server initialized: {server_info.get('serverInfo', {})}")

        # send initialized notification (no response expected)
        print("\n2. Sending initialized notification...")
        notification = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        process.stdin.write(notification.encode())
        process.stdin.flush()
        print("✓ Initialized notification sent")

        # 3. list tools request
        print("\n3. Sending tools/list request...")
        tools_response = send_request(
            process,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )

        if "result" not in tools_response:
            print(f"❌ tools/list failed: {tools_response}")
            sys.exit(1)

        tools = tools_response["result"].get("tools", [])
        tool_names = [tool["name"] for tool in tools]

        print(f"\n✓ Found {len(tools)} tools:")
        for name in sorted(tool_names):
            print(f"  - {name}")

        # 4. verify expected tools (IOProvider is always available)
        expected_tools = ["scaffold_data_app", "validate_data_app"]
        missing_tools = [tool for tool in expected_tools if tool not in tool_names]

        if missing_tools:
            print(f"\n❌ Missing expected tools: {missing_tools}")
            sys.exit(1)

        print(f"\n✓ All expected tools present: {expected_tools}")

        print("\n✅ Smoke test passed!")

    except Exception as e:
        print(f"\n❌ Smoke test failed: {e}")
        stderr = process.stderr.read().decode()
        if stderr:
            print(f"\nServer stderr:\n{stderr}")
        sys.exit(1)

    finally:
        process.terminate()
        process.wait(timeout=5)


if __name__ == "__main__":
    main()
