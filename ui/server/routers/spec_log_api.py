"""SPEC session log tail API.

Streams the latest SPEC log file to the dashboard's SPEC Output panel.
Reuses spec_logs.log_reader to find the newest file under BL_LOGS_DIR.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter

from beamline_tools.config import BL_LOGS_DIR, LOG_FILE_PATTERN

router = APIRouter(prefix="/api/spec_log", tags=["spec_log"])


_TAIL_MAX_BYTES = 64 * 1024
_INITIAL_TAIL_BYTES = 4 * 1024


def _latest_log_path() -> str | None:
    if not BL_LOGS_DIR.exists():
        return None
    candidates = list(Path(BL_LOGS_DIR).glob(LOG_FILE_PATTERN))
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(candidates[0])


@router.get("/tail")
async def tail(offset: int = -1):
    """Tail the most recent SPEC log file. Returns {path, offset, content, eof}.

    A negative `offset` is the "tail-mode" sentinel: the server seeks to
    the end of the file and returns only the trailing _INITIAL_TAIL_BYTES
    so callers don't replay months of history. Subsequent polls pass back
    the returned `offset` to stream new writes only.

    If the most-recent file changes between polls (new log started),
    the frontend will see a new `path` and should reset its offset to -1.
    """
    path = _latest_log_path()
    if not path or not os.path.exists(path):
        return {"path": None, "offset": 0, "content": "", "eof": 0}
    size = os.path.getsize(path)
    if offset < 0:
        offset = max(0, size - _INITIAL_TAIL_BYTES)
    elif offset > size:
        offset = 0
    end = min(size, offset + _TAIL_MAX_BYTES)
    with open(path, "rb") as f:
        f.seek(offset)
        chunk = f.read(end - offset)
    return {
        "path": path,
        "offset": end,
        "content": chunk.decode("utf-8", errors="replace"),
        "eof": size,
    }
