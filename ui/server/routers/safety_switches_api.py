"""Safety-switches API.

Reads/writes the file that gates every spec_cmd call. The path is **not**
computed here: it comes from `spec_cmd.safety_switches_path()`, the same
resolver the enforcement point uses, so this endpoint cannot drift into
writing a file nothing reads. `spec_cmd` re-reads it on every call, so a flip
here takes effect immediately without restarting any process.

Importing `beamline_tools` first is load-bearing — that package's __init__
pins BEAMTIMEHERO_SAFETY_SWITCHES for this deployment.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ui.server.schemas import SafetySwitchesIn

router = APIRouter(prefix="/api/safety_switches", tags=["safety"])

import beamline_tools  # noqa: F401  # pins the deployment path env vars
from beamtimehero_cli.spec_control.spec_cmd import safety_switches_path

_PATH = safety_switches_path()

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
def set_switches(payload: SafetySwitchesIn):
    """Update one or both switches; only fields present in the request change."""
    state = _read()
    for k in _KEYS:
        v = getattr(payload, k)
        if k in payload.model_fields_set and v is not None:
            state[k] = v
    try:
        _write_atomic(state)
    except OSError as e:
        raise HTTPException(500, f"failed to write safety switches: {e}")
    return state
