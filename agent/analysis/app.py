import streamlit as st
from pathlib import Path
from typing import Dict, List, Any
import os
from analysis.utils import extract_trajectories_from_dump
from analysis.trace_loader import TraceLoader
from collections import defaultdict
import re
import ujson as json


def get_trace_pattern(file_type: str) -> str:
    """Get the pattern for trace files based on selected type."""
    patterns = {
        "FSM enter states": "*fsm_enter.json",
        "FSM exit states": "*fsm_exit.json",
        "Top level agent": "*fsmtools_messages.json",
        "SSE events": "*sse_events*",
    }
    return patterns.get(file_type, "")


def group_sse_events(sse_files: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group SSE event files by trace ID and sort by sequence number."""
    trace_groups = defaultdict(list)

    for file_info in sse_files:
        trace_id = None
        sequence = None

        if file_info.get("is_local", True):
            # local pattern: {trace_id}_{timestamp}-sse_events_{sequence}.json
            filename = file_info["name"]
            match = re.match(r"([a-f0-9_]+)-sse_events_(\d+)\.json", filename)
            if match:
                trace_id, sequence = match.groups()
        else:
            # s3 pattern: app-{app_id}.req-{req_id}_{timestamp}/sse_events/{sequence}.json
            path = file_info["path"]
            match = re.match(r"(app-[a-f0-9-]+\.req-[a-f0-9-]+)_\d+/sse_events/(\d+)\.json", path)
            if match:
                trace_id, sequence = match.groups()
                # trace_id now has timestamp stripped (app-xxx.req-xxx)

        if trace_id and sequence is not None:
            file_info["trace_id"] = trace_id
            file_info["sequence"] = int(sequence)
            trace_groups[trace_id].append(file_info)

    # sort each group by sequence number (keep ALL events in sequence)
    for trace_id in trace_groups:
        trace_groups[trace_id].sort(key=lambda x: x["sequence"])

    return dict(trace_groups)


@st.cache_data
def get_status_icon(status: str) -> str:
    """Get cached status icon for better performance."""
    return "🟢" if status == "idle" else "🔄" if status == "running" else "⚪"


def display_sse_event(event_data: Dict[str, Any], sequence: int):
    """Display a single SSE event with proper formatting (optimized)."""
    status = event_data.get("status", "unknown")
    message = event_data.get("message", {})

    # create a status indicator with color
    status_color = get_status_icon(status)

    with st.expander(f"Event {sequence}: {status_color} {status.upper()}", expanded=False):
        col1, col2 = st.columns([1, 2])

        with col1:
            st.markdown("**Status:**")
            st.code(status)

            trace_id = event_data.get("trace_id")
            if trace_id:
                st.markdown("**Trace ID:**")
                st.code(trace_id[:8] + "...")

        with col2:
            if message:
                kind = message.get("kind", "Unknown")
                st.markdown(f"**Message Kind:** `{kind}`")

                # show content preview
                content = message.get("content", "")

        # show detailed message information in tabs
        if message:
            tab1, tab2, tab3, tab4 = st.tabs(["Content", "Agent State", "Diffs", "Metadata"])

            with tab1:
                content = message.get("content", "")
                if content:
                    try:
                        # try to parse as JSON first
                        if isinstance(content, str):
                            parsed_content = json.loads(content)
                            st.json(parsed_content)
                        else:
                            st.json(content)
                    except (json.JSONDecodeError, TypeError):
                        # fallback to markdown if not valid JSON
                        st.markdown(content)
                else:
                    st.info("No content available")

            with tab2:
                agent_state = message.get("agent_state") or message.get("agentState")
                if agent_state:
                    st.json(agent_state)
                else:
                    st.info("No agent state available")

            with tab3:
                unified_diff = message.get("unified_diff") or message.get("unifiedDiff")
                diff_stat = message.get("diff_stat") or message.get("diffStat")

                if unified_diff:
                    st.markdown("**Unified Diff:**")
                    st.code(unified_diff, language="diff")

                if diff_stat:
                    st.markdown("**Diff Statistics:**")
                    for stat in diff_stat:
                        st.write(f"📄 **{stat['path']}**: +{stat['insertions']} -{stat['deletions']}")

                if not unified_diff and not diff_stat:
                    st.info("No diff information available")

            with tab4:
                # pre-extract metadata for better performance
                metadata = {}
                for key in ["app_name", "commit_message", "complete_diff_hash", "completeDiffHash"]:
                    value = message.get(key)
                    if value:
                        metadata[key] = value

                if metadata:
                    st.json(metadata)
                else:
                    st.info("No metadata available")


def display_message(msg: Dict[str, Any], idx: int):
    """Display a single message in a nice format."""
    with st.expander(f"Message {idx + 1}: {msg.get('role', 'Unknown')}", expanded=False):
        content = msg.get("content", [""])
        if isinstance(content, list) and len(content) == 1:
            content = content[0]
        st.json(content)

        # Display additional fields
        excluded_fields = {"role", "content", "timestamp"}
        other_fields = {k: v for k, v in msg.items() if k not in excluded_fields}
        if other_fields:
            st.write("**Other fields:**")
            st.json(other_fields)


def display_top_level_message(msg: Dict[str, Any], idx: int):
    """Display a top-level agent message with better formatting for tool use."""
    role = msg.get("role", "Unknown")

    # both user and assistant blocks collapsed by default
    expanded = False

    with st.expander(f"Message {idx + 1}: {role.upper()}", expanded=expanded):
        content = msg.get("content", [])

        if isinstance(content, list):
            for i, item in enumerate(content):
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        st.markdown("**Text:**")
                        text_content = item.get("text", "")
                        # use markdown for assistant messages, plain text for others
                        if role == "assistant":
                            st.markdown(text_content)
                        else:
                            st.text(text_content)

                    elif item.get("type") == "tool_use":
                        st.markdown("**🔧 Tool Use:**")
                        col1, col2 = st.columns([1, 3])
                        with col1:
                            st.code(item.get("name", "Unknown"))
                        with col2:
                            st.json(item.get("input", {}))

                    elif item.get("type") == "tool_use_result":
                        st.markdown("**✅ Tool Result:**")
                        tool_use = item.get("tool_use", {})
                        tool_result = item.get("tool_result", {})

                        # show tool info
                        st.markdown(f"*Tool:* `{tool_use.get('name', 'Unknown')}`")

                        # show tool result content
                        if "content" in tool_result:
                            try:
                                # try to parse JSON content if it's a string
                                import json

                                result_content = tool_result["content"]
                                if isinstance(result_content, str):
                                    try:
                                        result_content = json.loads(result_content)
                                    except (json.JSONDecodeError, TypeError):
                                        pass

                                # display the content
                                with st.container():
                                    st.json(result_content)
                            except Exception:
                                st.text(tool_result["content"])

                    else:
                        # fallback for unknown types
                        st.json(item)

                # add separator between content items
                if i < len(content) - 1:
                    st.divider()
        else:
            # fallback for non-list content
            st.json(content)


def main():
    st.set_page_config(page_title="FSM Message Analyzer", layout="wide")
    st.title("FSM Message Trajectory Analyzer")

    # Sidebar for file selection
    with st.sidebar:
        st.header("Settings")

        # storage type selection
        storage_type = st.radio("Storage Type", options=["Local", "S3"], help="Choose where to load traces from")

        if storage_type == "Local":
            current_dir = os.path.dirname(os.path.abspath(__file__))
            default_traces_dir = str(Path(os.path.join(current_dir, "../traces")))

            # local directory configuration
            local_dir = st.text_input(
                "Local Directory Path",
                value=os.environ.get("TRACES_DIR", default_traces_dir),
                help="Enter the path to the directory containing traces",
            )
            traces_location = Path(local_dir)
            if not traces_location.exists():
                st.error(f"Traces directory not found: {traces_location}")
                return
        else:
            # s3 bucket selection
            s3_bucket_options = ["staging-agent-service-snapshots", "prod-agent-service-snapshots", "custom"]

            selected_bucket = st.selectbox(
                "S3 Bucket",
                options=s3_bucket_options,
                help="Select a predefined bucket or choose 'custom' to enter your own",
            )

            if selected_bucket == "custom":
                s3_bucket = st.text_input(
                    "Custom S3 Bucket Name",
                    value=os.environ.get("SNAPSHOT_BUCKET", ""),
                    help="Enter the S3 bucket name containing traces",
                )
                if not s3_bucket:
                    st.warning("Please enter an S3 bucket name")
                    return
            else:
                s3_bucket = selected_bucket

            traces_location = s3_bucket

        # initialize trace loader
        trace_loader = TraceLoader(str(traces_location))

        if not trace_loader.is_available:
            st.error(f"Storage location not available: {traces_location}")
            return

        # file type selection
        file_type = st.radio(
            "Trace Type",
            options=["FSM exit states", "FSM enter states", "SSE events"],
            help="Select the type of trace files to analyze. Note: Top level agent data is embedded in SSE events.",
        )

        # get file pattern
        pattern = get_trace_pattern(file_type)
        if not pattern:
            st.warning("Invalid trace type selected")
            return

        # get list of files
        fsm_files = trace_loader.list_trace_files([pattern])

        if not fsm_files:
            st.warning(f"No {file_type} files found")
            # add debug info for SSE events
            if file_type == "SSE events" and not trace_loader.is_local:
                st.info(f"Debug: Searching for pattern '{pattern}' in S3 bucket '{traces_location}'")
                # try to list any files at all to see what's there
                try:
                    all_files = trace_loader._list_s3_files(["*"])
                    st.write(f"Total files in bucket: {len(all_files)}")
                    if all_files:
                        sample_files = all_files[:10]
                        st.write("Sample file paths:")
                        for f in sample_files:
                            st.code(f["path"])
                except Exception as e:
                    st.error(f"Error listing files: {e}")
            return

        # special handling for SSE events
        if file_type == "SSE events":
            # group SSE events by trace ID
            trace_groups = group_sse_events(fsm_files)

            if not trace_groups:
                st.warning("No SSE event traces found")
                return

            # let user select a trace group
            def format_trace_option(trace_id):
                files = trace_groups[trace_id]
                files_count = len(files)
                latest_file = files[-1]  # get the last file (highest sequence)
                modified_str = latest_file["modified"].strftime("%Y-%m-%d %H:%M:%S")
                return f"{trace_id[:12]}... ({files_count} events, {modified_str})"

            # add trace filter
            trace_filter = st.text_input("Filter traces", placeholder="Enter text to filter trace IDs...")
            
            # filter traces based on user input
            trace_ids = list(trace_groups.keys())
            if trace_filter:
                filter_lower = trace_filter.lower()
                trace_ids = [tid for tid in trace_ids if filter_lower in tid.lower()]
            
            if not trace_ids:
                st.warning(f"No traces found matching '{trace_filter}'" if trace_filter else "No traces available")
                selected_trace_id = None
            else:
                selected_trace_id = st.selectbox(
                    "Select SSE Event Trace", options=trace_ids, format_func=format_trace_option
                )

            # store the selected trace group
            selected_file = None
            selected_trace_group = trace_groups[selected_trace_id] if selected_trace_id else []

        else:
            # File selection for other trace types
            def format_file_option(file_info):
                if file_info.get("is_local", True):
                    name, *rest = file_info["name"].split("-")
                    truncated = "-".join([name[:6] + "...", *rest])
                    return f"{truncated} ({file_info['modified'].strftime('%Y-%m-%d %H:%M:%S')})"
                else:
                    # for S3 files, show truncated trace ID + full filename
                    path_parts = file_info["path"].split("/")
                    if len(path_parts) > 1:
                        trace_id = path_parts[0]
                        filename = "/".join(path_parts[1:])
                        # truncate the trace ID (first two parts after - split)
                        id_parts = trace_id.split("-")
                        if len(id_parts) >= 2:
                            truncated_id = f"{id_parts[0][:6]}-{id_parts[1][:6]}..."
                        else:
                            truncated_id = trace_id[:12] + "..."
                        return f"{truncated_id}/{filename} ({file_info['modified'].strftime('%Y-%m-%d %H:%M:%S')})"
                    else:
                        # fallback for files without directory
                        return f"{file_info['path']} ({file_info['modified'].strftime('%Y-%m-%d %H:%M:%S')})"

            # add file filter
            file_filter = st.text_input("Filter files", placeholder="Enter text to filter files...")
            
            # filter files based on user input
            filtered_files = fsm_files
            if file_filter:
                filter_lower = file_filter.lower()
                filtered_files = [
                    f for f in fsm_files 
                    if filter_lower in f.get("name", "").lower() or filter_lower in f.get("path", "").lower()
                ]
            
            if not filtered_files:
                st.warning(f"No files found matching '{file_filter}'" if file_filter else "No files available")
                selected_file = None
            else:
                selected_file = st.selectbox("Select file", options=filtered_files, format_func=format_file_option)
            selected_trace_group = []

        # actors selection - only show for FSM enter/exit files
        if file_type in ["FSM exit states", "FSM enter states"]:
            actors_to_display = st.sidebar.multiselect(
                "Select Actors to Display",
                options=["Frontend", "Backend", "Draft", "Edit"],
                default=["Frontend", "Backend", "Draft", "Edit"],
            )
        else:
            actors_to_display = []
        # Process button
        process_label = "Process Trace" if file_type == "SSE events" else "Process File"
        
        # check if something is selected
        can_process = False
        if file_type == "SSE events":
            can_process = selected_trace_id is not None
        else:
            can_process = selected_file is not None
            
        if st.button(process_label, type="primary", disabled=not can_process):
            if file_type == "SSE events":
                st.session_state.current_trace_group = selected_trace_group
                st.session_state.selected_trace_id = selected_trace_id
                st.session_state.current_file = None
            else:
                st.session_state.current_file = selected_file
                st.session_state.current_trace_group = []

            st.session_state.trace_loader = trace_loader
            st.session_state.actors_to_display = actors_to_display
            st.session_state.file_type = file_type
            st.session_state.processing = True

    # Main content area
    if st.session_state.get("processing"):
        try:
            file_type = st.session_state.get("file_type", "")

            if file_type == "SSE events" and "current_trace_group" in st.session_state:
                # process SSE events
                trace_group = st.session_state.current_trace_group
                trace_id = st.session_state.selected_trace_id

                with st.spinner(f"Loading {len(trace_group)} SSE events..."):
                    trace_loader = st.session_state.trace_loader
                    sse_events = []

                    # load ALL SSE event files in the group (full sequence)
                    for file_info in trace_group:
                        try:
                            event_content = trace_loader.load_file(file_info)
                            # pre-process event for faster display
                            event_content["sequence"] = file_info["sequence"]
                            event_content["trace_id"] = file_info["trace_id"]

                            # extract commonly accessed fields for faster search
                            message = event_content.get("message", {})
                            event_content["_search_text"] = " ".join(
                                [
                                    str(event_content.get("status", "")),
                                    str(message.get("kind", "")),
                                    str(message.get("content", ""))[:500],  # limit content for search
                                ]
                            ).lower()

                            sse_events.append(event_content)
                        except Exception as e:
                            st.error(f"Error loading {file_info.get('name', file_info.get('path'))}: {str(e)}")

                    # sort by sequence number
                    sse_events.sort(key=lambda x: x.get("sequence", 0))

                    # extract top-level agent messages from LAST SSE event (has full collection)
                    fsm_messages = None
                    if sse_events:
                        last_event = sse_events[-1]  # get the last event in sequence
                        message = last_event.get("message", {})
                        agent_state = message.get("agent_state", {})
                        fsm_messages = agent_state.get("fsm_messages")

                    st.session_state.sse_events = sse_events
                    st.session_state.fsm_messages = fsm_messages
                    st.session_state.trace_type = "sse"
                    st.session_state.processing = False

            elif "current_file" in st.session_state and st.session_state.current_file:
                # process single file
                current_file = st.session_state.current_file
                with st.spinner(f"Processing {current_file['name']}..."):
                    # load the file content
                    trace_loader = st.session_state.trace_loader
                    file_content = trace_loader.load_file(current_file)

                    # determine trace type based on filename
                    filename = current_file["name"]

                    if "fsm_enter" in filename or "fsm_exit" in filename:
                        # FSM traces - use the existing extraction logic
                        messages = extract_trajectories_from_dump(file_content)
                        st.session_state.messages = messages
                        st.session_state.trace_type = "fsm"
                    elif "fsmtools_messages" in filename:
                        # top-level agent messages - store as special type
                        st.session_state.raw_content = file_content
                        st.session_state.trace_type = "fsmtools"
                    else:
                        # other traces - store raw content
                        st.session_state.raw_content = file_content
                        st.session_state.trace_type = "raw"

                    st.session_state.processing = False
        except Exception as e:
            st.error(f"Error processing: {str(e)}")
            st.session_state.processing = False

    # Display results
    if "trace_type" in st.session_state:
        # Show file path/name or trace ID
        if st.session_state.trace_type == "sse":
            trace_id = st.session_state.get("selected_trace_id", "Unknown")
            st.subheader(f"SSE Event Stream: {trace_id}")
        else:
            file_info = st.session_state.current_file
            if file_info:
                if file_info.get("is_local", True):
                    file_display = file_info["path"]
                else:
                    # for S3 files, show full S3 URL
                    bucket_name = st.session_state.trace_loader.bucket_or_path
                    file_display = f"s3://{bucket_name}/{file_info['path']}"
            else:
                file_display = "Unknown"

            st.markdown(f"**File:** `{file_display}`")

        if st.session_state.trace_type == "fsm" and "messages" in st.session_state:
            # FSM trace display logic
            messages = st.session_state.messages

            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Trajectories", len(messages))
            with col2:
                total_messages = sum(len(msgs) for msgs in messages.values())
                st.metric("Total Messages", total_messages)

            # Trajectory filter
            st.header("Trajectories")

            # Search box
            search_term = st.text_input("Search in messages", placeholder="Enter search term...")

            # Display trajectories
            actors_to_display = st.session_state.get("actors_to_display", [])

            for trajectory_name, trajectory_messages in messages.items():
                # if actors filter is specified, check if trajectory matches
                if actors_to_display:
                    is_displayed = False
                    for actor in actors_to_display:
                        if trajectory_name.startswith(actor.lower()):
                            is_displayed = True
                            break
                    if not is_displayed:
                        continue

                # Filter messages if search term is provided
                if search_term:
                    filtered_messages = [msg for msg in trajectory_messages if search_term.lower() in str(msg).lower()]
                    if not filtered_messages:
                        continue
                else:
                    filtered_messages = trajectory_messages

                with st.container():
                    st.subheader(f"📍 {trajectory_name}")
                    st.write(f"**{len(filtered_messages)} messages**")

                    # Display messages
                    for idx, msg in enumerate(filtered_messages):
                        display_message(msg, idx)

                    st.divider()

        elif st.session_state.trace_type == "fsmtools" and "raw_content" in st.session_state:
            # FSMTools messages display logic
            st.header("Top-Level Agent Messages")

            # parse the messages
            messages = st.session_state.raw_content
            if isinstance(messages, list):
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Total Messages", len(messages))
                with col2:
                    # count tool uses
                    tool_uses = sum(
                        1
                        for msg in messages
                        if isinstance(msg.get("content"), list)
                        for item in msg["content"]
                        if isinstance(item, dict) and item.get("type") == "tool_use"
                    )
                    st.metric("Tool Uses", tool_uses)

                # search box
                search_term = st.text_input("Search in messages", placeholder="Enter search term...")

                # display messages
                for idx, msg in enumerate(messages):
                    # filter if search term is provided
                    if search_term and search_term.lower() not in str(msg).lower():
                        continue

                    display_top_level_message(msg, idx)
            else:
                st.error("Invalid message format")

        elif st.session_state.trace_type == "sse" and "sse_events" in st.session_state:
            # SSE events display logic
            sse_events = st.session_state.sse_events

            st.header("Server-Sent Events Stream")

            # summary metrics (optimized - single pass)
            status_counts = {}
            kind_counts = {}

            for event in sse_events:
                # count statuses
                status = event.get("status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1

                # count message kinds
                message = event.get("message", {})
                kind = message.get("kind", "Unknown")
                kind_counts[kind] = kind_counts.get(kind, 0) + 1

            st.metric("Total Events", len(sse_events))

            # search functionality
            search_term = st.text_input(
                "Search in SSE events", placeholder="Search content, status, or message kind..."
            )

            # filter events by search term (optimized)
            filtered_events = sse_events
            if search_term:
                search_lower = search_term.lower()
                filtered_events = [event for event in sse_events if search_lower in event.get("_search_text", "")]

            if not filtered_events:
                if search_term:
                    st.warning(f"No events found matching '{search_term}'")
                else:
                    st.warning("No events to display")
            else:
                # timeline view - show events in sequence
                st.markdown("---")
                for event in filtered_events:
                    sequence = event.get("sequence", 0)
                    display_sse_event(event, sequence)

            # display top-level agent messages if available
            if "fsm_messages" in st.session_state and st.session_state.fsm_messages:
                st.markdown("---")
                st.header("Top-Level Agent Messages (from last SSE event)")

                fsm_messages = st.session_state.fsm_messages
                if isinstance(fsm_messages, list):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Total Messages", len(fsm_messages))
                    with col2:
                        # count tool uses
                        tool_uses = sum(
                            1
                            for msg in fsm_messages
                            if isinstance(msg.get("content"), list)
                            for item in msg["content"]
                            if isinstance(item, dict) and item.get("type") == "tool_use"
                        )
                        st.metric("Tool Uses", tool_uses)

                    # display messages
                    for idx, msg in enumerate(fsm_messages):
                        display_top_level_message(msg, idx)
                else:
                    st.info("FSM messages found but not in expected list format")

        elif st.session_state.trace_type == "raw" and "raw_content" in st.session_state:
            # Raw trace display logic - show plain JSON
            st.header("Raw Trace Data")

            # Display the raw JSON content
            with st.expander("Full JSON Content", expanded=True):
                st.json(st.session_state.raw_content)

    else:
        st.info("👈 Select an FSM checkpoint file from the sidebar to begin analysis")


if __name__ == "__main__":
    main()
