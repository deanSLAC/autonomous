"""Insight API — turn ring buffer, simulation status, system prompt.

Powers the `/insight` page. The ring buffer is filled by the
ConversationService turn-sink registered from app.py and is also the
source for the WebSocket `turn_complete` events (broadcast in parallel,
not via this module).
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ui.config import CONTEXT_DIR

router = APIRouter(prefix="/api/insight", tags=["insight"])


# ---------------------------------------------------------------------------
# Ring buffer of recent turns
# ---------------------------------------------------------------------------

_MAX_TURNS = 100
_turns: deque[dict] = deque(maxlen=_MAX_TURNS)
_lock = threading.Lock()


def record_turn(payload: dict) -> dict:
    """Stamp + store one turn. Returns the stored entry (with id/ts)."""
    entry = dict(payload)
    entry.setdefault("id", uuid.uuid4().hex[:12])
    entry.setdefault("ts", time.time())
    with _lock:
        _turns.append(entry)
    return entry


def list_turns(limit: int = 50) -> list[dict]:
    with _lock:
        items = list(_turns)
    items.reverse()
    return items[:limit]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/turns")
def turns(limit: int = 50) -> dict:
    return {"turns": list_turns(limit=limit)}


@router.get("/simulation")
def simulation_status() -> dict:
    info: dict[str, Any] = {"enabled": False}
    try:
        import simulation
        info = simulation.status()
    except Exception as e:
        info["error"] = str(e)

    # Surface the mock screen positions if available.
    try:
        from beamline_tools.spec.screen_client import _MockScreen
        info["positions"] = dict(_MockScreen._positions)
        info["last_filename"] = _MockScreen._filename
    except Exception:
        pass
    return info


@router.get("/system_prompt")
def system_prompt() -> dict:
    fp = Path(CONTEXT_DIR) / "system_prompt.txt"
    if not fp.exists():
        raise HTTPException(404, "system_prompt.txt not found")
    return {"path": str(fp), "text": fp.read_text()}
