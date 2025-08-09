import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


def maybe_pluralize(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


async def notify_if_callback(
    event_callback: Callable[[str], Awaitable[None]] | None,
    message: str,
    error_context: str = "notification",
) -> None:
    """
    Utility function to send event notifications if callback is available.

    Args:
        event_callback: Optional callback function to send events
        message: The message to send to the callback
        error_context: Context description for error logging (default: "notification")
    """
    if event_callback:
        try:
            await event_callback(message)
        except Exception as e:
            logger.warning(f"Failed to emit {error_context}: {e}")


async def notify_stage(
    event_callback: Callable[[str], Awaitable[None]] | None,
    stage: str,
    status: str = "in_progress",
) -> None:
    """
    Send consolidated stage-based notifications.

    Args:
        event_callback: Optional callback function to send events
        stage: The stage name (e.g., "building handlers", "running tests")
        status: Stage status - "in_progress", "completed", "failed"
    """
    if not event_callback:
        return

    # Create simple, consolidated messages without excessive emojis
    if status == "in_progress":
        message = f"{stage}..."
    elif status == "completed":
        message = f"{stage}"
    elif status == "failed":
        message = f"{stage}"
    else:
        message = f"{stage}"

    try:
        await event_callback(message)
    except Exception as e:
        logger.warning(f"Failed to emit stage notification for '{stage}': {e}")


def get_file_emoji(file_path: str) -> str:
    """
    Get appropriate emoji for file type based on file extension.

    Args:
        file_path: Path to the file

    Returns:
        Emoji string for the file type
    """
    if (
        file_path.endswith(".ts")
        or file_path.endswith(".tsx")
        or file_path.endswith(".py")
    ):
        return "📝"
    elif file_path.endswith(".css"):
        return "🎨"
    elif file_path.endswith(".json"):
        return "⚙️"
    else:
        return "📄"


async def notify_files_processed(
    event_callback: Callable[[str], Awaitable[None]] | None,
    files_written: list[str],
    edit_count: int = 0,
    new_count: int = 0,
    operation_type: str = "generated",
) -> None:
    """
    Send user-friendly notification about processed files.

    Args:
        event_callback: Optional callback function to send events
        files_written: List of file paths that were written
        edit_count: Number of files that were edited (for edit operations)
        new_count: Number of new files that were created (for edit operations)
        operation_type: Type of operation ("generated" for new generation, "processed" for edits)
    """
    if not files_written:
        return

    # Create file summary with emojis
    file_summary = []
    for file in files_written[:3]:  # Show first 3 files
        emoji = get_file_emoji(file)
        file_summary.append(f"{emoji} {file}")

    more_files = f" (+{len(files_written) - 3} more)" if len(files_written) > 3 else ""

    # Create appropriate message based on operation type
    if operation_type == "generated":
        progress_msg = (
            f"✨ Created {len(files_written)} {maybe_pluralize(len(files_written), 'file', 'files')}:\n"
            + "\n".join(file_summary)
            + more_files
        )
        error_context = "progress update"
    else:  # edit operations
        if edit_count > 0 and new_count > 0:
            progress_msg = (
                f"✏️ Edited {edit_count} {maybe_pluralize(edit_count, 'file', 'files')} and created {new_count} {maybe_pluralize(new_count, 'file', 'files')}:\n"
                + "\n".join(file_summary)
                + more_files
            )
        elif edit_count > 0:
            progress_msg = (
                f"✏️ Edited {edit_count} {maybe_pluralize(edit_count, 'file', 'files')}:\n"
                + "\n".join(file_summary)
                + more_files
            )
        else:
            progress_msg = (
                f"✨ Created {new_count} {maybe_pluralize(new_count, 'file', 'files')}:\n"
                + "\n".join(file_summary)
                + more_files
            )
        error_context = "edit progress"

    await notify_if_callback(event_callback, progress_msg, error_context)
