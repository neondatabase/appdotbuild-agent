import ujson as json
import boto3
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
import os
from log import get_logger

logger = get_logger(__name__)


class TraceLoader:
    """Utility class to load traces from either local filesystem or S3."""

    def __init__(self, bucket_or_path: str):
        self.bucket_or_path = bucket_or_path

        # check if this is a local directory
        if os.path.exists(bucket_or_path) and os.path.isdir(bucket_or_path):
            self.is_local = True
            self.is_available = True
        else:
            self.is_local = False
            self.is_available = self._check_s3_available()

    def _check_s3_available(self) -> bool:
        """Check if S3 bucket is available."""
        if not self.bucket_or_path:
            logger.info("No S3 bucket provided, using local filesystem only")
            return False

        try:
            s3_client = boto3.client("s3")
            s3_client.head_bucket(Bucket=self.bucket_or_path)
            logger.info(f"S3 bucket {self.bucket_or_path} is available")
            return True
        except Exception as e:
            logger.info(f"S3 bucket not available: {e}")
            return False

    def list_trace_files(self, patterns: List[str]) -> List[Dict[str, Any]]:
        """List all trace files matching the given patterns."""
        if self.is_local:
            return self._list_local_files(patterns)
        elif self.is_available:
            return self._list_s3_files(patterns)
        else:
            return []

    def _list_local_files(self, patterns: List[str]) -> List[Dict[str, Any]]:
        """List local files matching patterns."""
        files = []
        directory = Path(self.bucket_or_path)

        for pattern in patterns:
            for file_path in directory.glob(pattern):
                files.append(
                    {
                        "path": str(file_path),
                        "name": file_path.name,
                        "modified": datetime.fromtimestamp(file_path.stat().st_mtime),
                        "size": file_path.stat().st_size,
                        "is_local": True,
                    }
                )

        return sorted(files, key=lambda x: x["modified"], reverse=True)

    def _list_s3_files(self, patterns: List[str]) -> List[Dict[str, Any]]:
        """List S3 objects matching patterns."""
        files = []
        s3_client = boto3.client("s3")

        try:
            # optimize for SSE events by using prefix-based filtering
            if len(patterns) == 1 and patterns[0] == "*sse_events*":
                files.extend(self._list_s3_sse_events(s3_client))
            else:
                # fallback to full bucket scan for other patterns
                paginator = s3_client.get_paginator("list_objects_v2")
                pages = paginator.paginate(Bucket=self.bucket_or_path)

                for page in pages:
                    if "Contents" not in page:
                        continue

                    for obj in page["Contents"]:
                        key = obj["Key"]
                        name = os.path.basename(key)
                        # check if the file matches any of the patterns
                        for pattern in patterns:
                            if self._matches_s3_pattern(key, pattern):
                                files.append(
                                    {
                                        "path": key,
                                        "name": name,
                                        "modified": obj["LastModified"],
                                        "size": obj["Size"],
                                        "is_local": False,
                                    }
                                )
                                break

        except Exception as e:
            logger.exception(f"Error listing S3 files: {e}")

        return sorted(files, key=lambda x: x["modified"], reverse=True)

    def _list_s3_sse_events(self, s3_client) -> List[Dict[str, Any]]:
        """Fast single-call listing for SSE events with client-side filtering."""
        files = []

        try:
            # single paginated call to list all objects, filter for sse_events
            paginator = s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket_or_path)

            for page in pages:
                if "Contents" not in page:
                    continue

                for obj in page["Contents"]:
                    key = obj["Key"]
                    # fast string check: only process SSE event files
                    if "/sse_events/" in key and key.endswith(".json"):
                        files.append(
                            {
                                "path": key,
                                "name": os.path.basename(key),
                                "modified": obj["LastModified"],
                                "size": obj["Size"],
                                "is_local": False,
                            }
                        )

        except Exception as e:
            logger.exception(f"Error listing SSE events: {e}")

        return files

    def _matches_pattern(self, filename: str, pattern: str) -> bool:
        """Check if filename matches the glob pattern."""
        # simple pattern matching for common cases
        if pattern.startswith("*") and pattern.endswith(".json"):
            suffix = pattern[1:]  # remove the *
            return filename.endswith(suffix)

        if pattern.startswith("*") and pattern.endswith("*"):
            suffix = pattern[1:-1]
            return suffix in filename

        return False

    def _matches_s3_pattern(self, key: str, pattern: str) -> bool:
        """Check if S3 key matches the pattern, considering full path structure."""
        # for SSE events pattern "*sse_events*", match both local and S3 patterns
        if pattern == "*sse_events*":
            # S3 pattern: {trace_id}/sse_events/{sequence}.json
            return "/sse_events/" in key and key.endswith(".json")

        # fallback to filename-only matching
        filename = os.path.basename(key)
        return self._matches_pattern(filename, pattern)

    def load_file(self, file_info: Dict[str, Any]) -> Dict[str, Any]:
        """Load a trace file from either local filesystem or S3."""
        if file_info.get("is_local", True):
            return self._load_local_file(file_info["path"])
        else:
            return self._load_s3_file(file_info["path"])

    def _load_local_file(self, path: str) -> Dict[str, Any]:
        """Load a file from local filesystem."""
        with open(path, "r") as f:
            return json.load(f)

    def _load_s3_file(self, key: str) -> Dict[str, Any]:
        """Load a file from S3."""
        s3_client = boto3.client("s3")

        try:
            response = s3_client.get_object(Bucket=self.bucket_or_path, Key=key)
            content = response["Body"].read()
            return json.loads(content)
        except Exception:
            logger.exception(f"Error loading S3 file {key}")
            raise
