"""Safety-switches API.

Reads/writes `beamline_tools/safety_switches.json`. The file gates every
spec_cmd call (see beamline_tools/spec_control/spec_cmd.py:_safety_check),
re-read on every call, so a flip here takes effect immediately without
restarting any process.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/safety_switches", tags=["safety"])

_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "beamline_tools" / "safety_switches.json"
)

_KEYS = ("spec_read_enabled", "spec_write_enabled")


def _read() -> dict:
    try:
        with open(_PATH) as f:
            data = json.load(f) or {}
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    return {k: bool(data.get(k, True)) for k in _KEYS}


def _write_atomic(state: dict) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".safety_switches.", suffix=".json", dir=str(_PATH.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, _PATH)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


@router.get("")
def get_switches():
    return _read()


@router.post("")
def set_switches(payload: dict):
    """Update one or both switches. Unrecognized keys are ignored."""
    state = _read()
    for k in _KEYS:
        if k in payload:
            state[k] = bool(payload[k])
    try:
        _write_atomic(state)
    except OSError as e:
        raise HTTPException(500, f"failed to write safety switches: {e}")
    return state
