"""Log file operations for beamline control logs."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from beamline_tools.scans.bl_config import BL_LOGS_DIR, LOG_FILE_PATTERN, MAX_FILE_SIZE_BYTES, MAX_LOG_LINES

logger = logging.getLogger(__name__)


def list_logs(limit=20):
    """List available log files, most recent first."""
    if not BL_LOGS_DIR.exists():
        return []

    files = list(BL_LOGS_DIR.glob(LOG_FILE_PATTERN))
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    return [
        {
            "name": f.name,
            "path": str(f),
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            "size_bytes": f.stat().st_size,
        }
        for f in files[:limit]
    ]


def read_log(log_name, tail_lines=None):
    """Read contents of a log file, optionally just the last N lines."""
    log_path = BL_LOGS_DIR / log_name

    if not log_path.exists() or not log_path.is_file():
        return None

    # Security check
    try:
        log_path.resolve().relative_to(BL_LOGS_DIR.resolve())
    except ValueError:
        return None

    if tail_lines:
        lines = []
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            block_size = 8192
            data = b""
            while len(lines) <= tail_lines and size > 0:
                read_size = min(block_size, size)
                size -= read_size
                f.seek(size)
                data = f.read(read_size) + data
                lines = data.split(b"\n")
        return b"\n".join(lines[-tail_lines:]).decode(errors="replace")

    if log_path.stat().st_size > MAX_FILE_SIZE_BYTES:
        return read_log(log_name, tail_lines=MAX_LOG_LINES)

    return log_path.read_text(errors="replace")


def get_latest_log_entries(lines=100):
    """Get the last N lines from the most recent log file."""
    if not BL_LOGS_DIR.exists():
        return None

    log_files = list(BL_LOGS_DIR.glob(LOG_FILE_PATTERN))
    if not log_files:
        return None

    latest = max(log_files, key=lambda f: f.stat().st_mtime)
    return {
        "name": latest.name,
        "modified": datetime.fromtimestamp(latest.stat().st_mtime).isoformat(),
        "content": read_log(latest.name, tail_lines=lines),
    }


def search_logs(query, max_results=50):
    """Search across log files for a string."""
    results = []

    if not BL_LOGS_DIR.exists():
        return results

    for log_file in BL_LOGS_DIR.glob(LOG_FILE_PATTERN):
        try:
            with open(log_file, "r", errors="replace") as f:
                for line_num, line in enumerate(f, 1):
                    if query.lower() in line.lower():
                        results.append({
                            "file": log_file.name,
                            "line_number": line_num,
                            "content": line.strip(),
                        })
                        if len(results) >= max_results:
                            return results
        except Exception as e:
            logger.warning("Could not read log file %s: %s", log_file.name, e)
            continue

    return results
