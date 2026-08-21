#!/usr/bin/env python3
import argparse
import json
import logging
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class SessionInfo:
    session_id: str
    project: str
    start_time: int
    end_time: int
    message_count: int
    edda_tool_usage: set[str]
    first_message: str
    records: list[dict]


def extract_matching_tools(record: dict) -> set[str]:
    tools = set()

    # recursively search for tool_use blocks with name field
    def walk(obj):
        match obj:
            case {"type": "tool_use", "name": str(name)} if name.startswith(("mcp__edda", "mcp__databricks")):
                tools.add(name)
            case dict():
                for value in obj.values():
                    walk(value)
            case list():
                for item in obj:
                    walk(item)

    walk(record)
    return tools


def parse_session_file(session_file: Path) -> SessionInfo | None:
    records = []
    edda_tools = set()
    start_time = None
    end_time = None
    first_message = ""
    session_id = None
    project = None

    try:
        with session_file.open("r") as f:
            for line in f:
                if not line.strip():
                    continue

                record = json.loads(line)
                records.append(record)

                if session_id is None:
                    session_id = record.get("sessionId")
                if project is None:
                    project = record.get("cwd")

                timestamp_str = record.get("timestamp")
                if timestamp_str:
                    ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    timestamp_ms = int(ts.timestamp() * 1000)

                    if start_time is None:
                        start_time = timestamp_ms
                    end_time = timestamp_ms

                edda_tools.update(extract_matching_tools(record))

                if not first_message and record.get("type") == "user":
                    msg = record.get("message", {})
                    match msg:
                        case {"content": str(content)}:
                            first_message = content[:200]
                        case {"content": [{"text": str(text)}, *_]}:
                            first_message = text[:200]

        if not records:
            return None

        if not session_id or not project or start_time is None:
            logger.warning(
                f"skipping {session_file.name}: missing required fields "
                f"(session_id={session_id}, project={project}, start_time={start_time})"
            )
            return None

        if end_time is None:
            end_time = start_time

        return SessionInfo(
            session_id=session_id,
            project=project,
            start_time=start_time,
            end_time=end_time,
            message_count=len([r for r in records if r.get("type") in ("user", "assistant")]),
            edda_tool_usage=edda_tools,
            first_message=first_message,
            records=records,
        )
    except json.JSONDecodeError as e:
        logger.error(f"invalid JSON in {session_file.name}: {e}")
        return None
    except OSError as e:
        logger.error(f"failed to read {session_file.name}: {e}")
        return None
    except Exception as e:
        logger.error(f"unexpected error parsing {session_file.name}: {e}")
        return None


def parse_all_sessions(
    projects_dir: Path,
    min_date: datetime | None = None,
    max_date: datetime | None = None,
    project_pattern: str | None = None,
) -> dict[str, tuple[SessionInfo, str]]:
    sessions: dict[str, tuple[SessionInfo, str]] = {}

    if not projects_dir.exists():
        logger.error(f"projects directory does not exist: {projects_dir}")
        return sessions

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        source_project_name = project_dir.name

        if project_pattern and project_pattern.lower() not in source_project_name.lower():
            continue

        for session_file in project_dir.glob("*.jsonl"):
            session_info = parse_session_file(session_file)
            if not session_info:
                continue

            session_datetime = datetime.fromtimestamp(session_info.start_time / 1000)

            if min_date and session_datetime < min_date:
                continue
            if max_date and session_datetime > max_date:
                continue

            sessions[session_info.session_id] = (session_info, source_project_name)

    return sessions


def format_timestamp(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M:%S")


def format_duration(start_ms: int, end_ms: int) -> str:
    duration_sec = (end_ms - start_ms) / 1000
    match duration_sec:
        case d if d < 60:
            return f"{d:.0f}s"
        case d if d < 3600:
            return f"{d / 60:.1f}m"
        case d:
            return f"{d / 3600:.1f}h"


def write_session_file(session: SessionInfo, output_dir: Path, source_project_name: str):
    project_dir = output_dir / source_project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{session.session_id}.json"
    filepath = project_dir / filename

    # remove redundant sessionId from records
    cleaned_records = []
    for record in session.records:
        cleaned = {k: v for k, v in record.items() if k != "sessionId"}
        cleaned_records.append(cleaned)

    session_data = {
        "metadata": {
            "project": session.project,
            "session_id": session.session_id,
            "start_time": format_timestamp(session.start_time),
            "start_time_ms": session.start_time,
            "end_time": format_timestamp(session.end_time),
            "end_time_ms": session.end_time,
            "duration": format_duration(session.start_time, session.end_time),
            "message_count": session.message_count,
            "total_records": len(session.records),
            "matching_tools": sorted(session.edda_tool_usage),
        },
        "records": cleaned_records,
    }

    try:
        with filepath.open("w") as f:
            json.dump(session_data, f, ensure_ascii=False)
    except OSError as e:
        logger.error(f"failed to write {filepath}: {e}")
        raise


def print_summary(sessions: dict[str, tuple[SessionInfo, str]]):
    total = len(sessions)
    matching = sum(1 for s, _ in sessions.values() if s.edda_tool_usage)
    other = total - matching

    tool_counter = Counter()
    for session_info, _ in sessions.values():
        tool_counter.update(session_info.edda_tool_usage)

    total_duration_sec = sum((s.end_time - s.start_time) / 1000 for s, _ in sessions.values())
    avg_duration_sec = total_duration_sec / total if total > 0 else 0

    logger.info(f"total sessions: {total}")
    logger.info(f"sessions with mcp__edda or mcp__databricks: {matching}")
    logger.info(f"other sessions: {other}")
    logger.info(f"avg session duration: {format_duration(0, int(avg_duration_sec * 1000))}")

    if tool_counter:
        logger.info("\ntool usage frequency:")
        for tool, count in tool_counter.most_common():
            logger.info(f"  {tool}: {count}")


def main():
    parser = argparse.ArgumentParser(
        description="parse Claude Code conversation history and analyze tool usage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s                          # all sessions
  %(prog)s --days 7                 # last 7 days
  %(prog)s --project agent          # projects containing 'agent'
  %(prog)s --days 30 --project mcp  # combine filters
        """,
    )
    parser.add_argument(
        "--days",
        type=int,
        metavar="N",
        help="filter sessions from last N days",
        default=3,
    )
    parser.add_argument(
        "--project",
        type=str,
        metavar="PATTERN",
        help="filter projects by pattern (case-insensitive substring match)",
    )
    parser.add_argument(
        "--output",
        type=str,
        metavar="DIR",
        default="/tmp/claude_sessions",
        help="output directory (default: /tmp/claude_sessions)",
    )

    args = parser.parse_args()

    projects_dir = Path.home() / ".claude" / "projects"
    output_dir = Path(args.output)

    min_date = None
    if args.days:
        min_date = datetime.now() - timedelta(days=args.days)

    if not projects_dir.exists():
        logger.error(f"projects directory not found: {projects_dir}")
        return

    try:
        output_dir.mkdir(exist_ok=True, parents=True)
    except OSError as e:
        logger.error(f"failed to create output directory {output_dir}: {e}")
        return

    logger.info(f"output directory: {output_dir}")
    logger.info(f"parsing sessions from {projects_dir}...")
    if min_date:
        logger.info(f"filtering sessions from last {args.days} days")
    if args.project:
        logger.info(f"filtering projects matching: '{args.project}'")

    sessions = parse_all_sessions(projects_dir, min_date=min_date, project_pattern=args.project)

    # filter to only sessions with mcp__edda or mcp__databricks tools
    sessions = {sid: (info, proj) for sid, (info, proj) in sessions.items() if info.edda_tool_usage}

    logger.info(f"writing {len(sessions)} sessions with matching tools...")

    for session_info, source_project_name in sessions.values():
        write_session_file(session_info, output_dir, source_project_name)

    logger.info(f"files written to: {output_dir}")
    print_summary(sessions)

    # create zip archive
    archive_path = output_dir / "archive"
    logger.info("creating zip archive...")
    shutil.make_archive(str(archive_path), "zip", output_dir)

    zip_file = f"{archive_path}.zip"
    logger.info(f"\nrelevant logs are stored in {zip_file}")


if __name__ == "__main__":
    main()
