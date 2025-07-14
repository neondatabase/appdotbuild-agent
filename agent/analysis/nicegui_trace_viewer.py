#!/usr/bin/env python3
"""Interactive LLM Conversation Chain Viewer"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime
import re


def format_content(content, format="display"):
    """Format message content for display"""
    if not content:
        return ""

    # handle list content directly
    if isinstance(content, list):
        # check if this is a simple text message
        if (
            len(content) == 1
            and isinstance(content[0], dict)
            and content[0].get("type") == "text"
        ):
            return content[0].get("text", "")

        # handle mixed content
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "tool_use":
                    tool_name = item.get("name", "unknown")
                    tool_input = item.get("input", {})
                    tool_part = f"🔧 **{tool_name}**"
                    if tool_input:
                        # format input as JSON in markdown code block
                        input_json = json.dumps(tool_input, indent=2)
                        tool_part += f"\n```json\n{input_json}\n```"
                    parts.append(tool_part)
                elif item.get("type") == "tool_use_result":
                    tool_name = item.get("tool_use", {}).get("name", "unknown")
                    is_error = item.get("tool_result", {}).get("is_error", False)
                    status = "❌" if is_error else "✅"
                    result_content = item.get("tool_result", {}).get("content", "")
                    result_part = f"{status} **{tool_name}**"
                    if result_content:
                        # format result content
                        result_part += f"\n```\n{result_content}\n```"
                    parts.append(result_part)
        return "\n".join(parts).strip()

    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return format_content(parsed, format)
        except json.JSONDecodeError:
            pass

    content_str = str(content)
    if format == "preview":
        return content_str[:100] + "..." if len(content_str) > 100 else content_str
    return content_str


def extract_nodes(data: Dict[str, Any]) -> List[Dict]:
    """Extract all nodes with messages from the data"""
    nodes = []
    actors = data.get("actors", [])

    if isinstance(actors, list):
        for actor in actors:
            for node in actor.get("data", []):
                if node.get("data", {}).get("messages"):
                    nodes.append(node)
    else:
        for actor in actors.values():
            for node in actor.get("data", []):
                if node.get("data", {}).get("messages"):
                    nodes.append(node)

    return nodes


def build_conversation_chains(nodes: List[Dict]) -> List[List[Dict]]:
    """Build conversation chains from leaf to root"""
    node_map = {node["id"]: node for node in nodes}

    # find leaf nodes
    all_ids = set(node["id"] for node in nodes)
    parent_ids = set(node.get("parent") for node in nodes if node.get("parent"))
    leaf_ids = all_ids - parent_ids

    # build chains from leaves to roots
    chains = []
    for leaf_id in leaf_ids:
        chain = []
        current_id = leaf_id

        while current_id and current_id in node_map:
            node = node_map[current_id]
            chain.insert(0, node)
            current_id = node.get("parent")

        if chain:
            chains.append(chain)

    return chains


def get_chain_summary(chain: List[Dict]) -> Dict:
    """Get summary info about a chain"""
    total_messages = 0
    user_messages = 0
    assistant_messages = 0
    tools_used = set()

    first_message = None
    last_message = None

    for node in chain:
        messages = node.get("data", {}).get("messages", [])
        total_messages += len(messages)

        for msg in messages:
            role = msg.get("role", "")
            if role == "user":
                user_messages += 1
            elif role == "assistant":
                assistant_messages += 1

            if first_message is None:
                first_message = msg
            last_message = msg

            # extract tools
            content = str(msg.get("content", ""))
            if "tool_use" in content:
                tool_matches = re.findall(r'"name":\s*"([^"]+)"', content)
                tools_used.update(tool_matches)

    return {
        "length": len(chain),
        "total_messages": total_messages,
        "user_messages": user_messages,
        "assistant_messages": assistant_messages,
        "tools_used": list(tools_used),
        "first_message": first_message,
        "last_message": last_message,
    }


def display_chain_list(chains: List[List[Dict]]):
    """Display list of available chains"""
    print("📋 CONVERSATION CHAINS")
    print("=" * 60)

    for i, chain in enumerate(chains, 1):
        summary = get_chain_summary(chain)

        print(
            f"\n{i}. Chain {i} ({summary['length']} nodes, {summary['total_messages']} messages)"
        )

        if summary["first_message"]:
            role = summary["first_message"].get("role", "unknown")
            preview = format_content(
                summary["first_message"].get("content", ""), "preview"
            )
            print(f"   Start: [{role}] {preview}")

        if summary["tools_used"]:
            print(
                f"   Tools: {', '.join(summary['tools_used'][:3])}"
                + ("..." if len(summary["tools_used"]) > 3 else "")
            )

        print(
            f"   Messages: {summary['user_messages']} user, {summary['assistant_messages']} assistant"
        )


def display_conversation(chain: List[Dict], chain_num: int):
    """Display a single conversation with nice formatting"""
    print(f"\n{'=' * 80}")
    print(f"CONVERSATION {chain_num}")
    print(f"{'=' * 80}")

    summary = get_chain_summary(chain)
    print(f"📊 {summary['length']} nodes • {summary['total_messages']} messages")
    if summary["tools_used"]:
        print(f"🔧 Tools: {', '.join(summary['tools_used'])}")
    print()

    message_count = 0

    for node_idx, node in enumerate(chain):
        messages = node.get("data", {}).get("messages", [])

        for msg in messages:
            message_count += 1
            role = msg.get("role", "unknown")
            timestamp = msg.get("timestamp", "")

            # format role with emoji
            if role == "user":
                role_display = "👤 USER"
            elif role == "assistant":
                role_display = "🤖 ASSISTANT"
            else:
                role_display = f"📝 {role.upper()}"

            # format timestamp
            time_str = ""
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M:%S")
                except ValueError:
                    pass

            print(f"{message_count}. {role_display} {time_str}")
            print("-" * 40)

            content = format_content(msg.get("content", ""), "display")
            print(content)
            print()


def display_summary(chains: List[List[Dict]]):
    """Display summary statistics"""
    print("\n📊 SUMMARY STATISTICS")
    print("=" * 50)

    total_nodes = sum(len(chain) for chain in chains)
    total_messages = sum(get_chain_summary(chain)["total_messages"] for chain in chains)

    print(f"Total chains: {len(chains)}")
    print(f"Total nodes: {total_nodes}")
    print(f"Total messages: {total_messages}")

    if chains:
        lengths = [len(chain) for chain in chains]
        print(f"Average chain length: {sum(lengths) / len(lengths):.1f} nodes")
        print(f"Longest chain: {max(lengths)} nodes")
        print(f"Shortest chain: {min(lengths)} nodes")

    # tool usage
    all_tools = set()
    for chain in chains:
        summary = get_chain_summary(chain)
        all_tools.update(summary["tools_used"])

    if all_tools:
        print(f"Tools used: {', '.join(sorted(all_tools))}")


def main():
    if len(sys.argv) != 2:
        print("🔍 LLM Conversation Chain Viewer")
        print("Usage: llm_viewer.py <json_file>")
        sys.exit(1)

    file_path = Path(sys.argv[1])

    if not file_path.exists():
        print(f"❌ Error: File {file_path} not found")
        sys.exit(1)

    try:
        with open(file_path, "r") as f:
            data = json.load(f)

        nodes = extract_nodes(data)
        chains = build_conversation_chains(nodes)
        chains.sort(key=len, reverse=True)

        # show all chains
        for i, chain in enumerate(chains, 1):
            display_conversation(chain, i)
            if i < len(chains):
                print("\n" + "=" * 100)
                print("=" * 100)
                print()

    except json.JSONDecodeError as e:
        print(f"❌ Error parsing JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
