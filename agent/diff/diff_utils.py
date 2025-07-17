"""Diff utilities for handling unified diffs and computing diff statistics."""

import logging
from typing import Dict, List, Optional

from api.agent_server.models import DiffStatEntry

logger = logging.getLogger(__name__)


def compute_diff_stat(diff: str) -> List[DiffStatEntry]:
    """Return a list of DiffStatEntry parsed from a unified diff string."""
    stats: dict[str, Dict[str, int]] = {}
    current_file: Optional[str] = None

    for line in diff.splitlines():
        if line.startswith("diff --git"):
            parts = line.split(" ")
            if len(parts) >= 3:
                # path like a/path b/path
                file_b = parts[3]
                if file_b.startswith("b/"):
                    file_b = file_b[2:]
                current_file = file_b
                stats[current_file] = {"insertions": 0, "deletions": 0}
        elif current_file and line.startswith("+++"):
            # ignore header lines
            continue
        elif current_file and line.startswith("---"):
            continue
        elif current_file:
            if line.startswith("+") and not line.startswith("+++"):
                stats[current_file]["insertions"] += 1
            elif line.startswith("-") and not line.startswith("---"):
                stats[current_file]["deletions"] += 1

    return [
        DiffStatEntry(path=path, insertions=s["insertions"], deletions=s["deletions"])
        for path, s in stats.items()
    ] 