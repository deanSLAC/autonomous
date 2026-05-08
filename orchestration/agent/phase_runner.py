"""Per-phase agent process manager.

The dashboard now spawns one Claude-CLI subprocess per phase tile (Beamline
Alignment, Sample Alignment, Data Collection) instead of running a single
master orchestrator loop. Each tile maps to a shell script under scripts/
that wraps `claude -p` with the right system prompt + tool allowlist.

This module:

  * Tracks the running subprocess per phase slug ({slug: Popen}).
  * Tees the script's combined stdout/stderr to logs/phase_<slug>_<ts>.log.
  * Cleans up the slot when the process exits (a small daemon thread
    waits on each Popen).

Public API:

  start(slug)          → spawn or fail with ValueError("already running")
  kill(slug)           → SIGTERM + clean up
  status_all()         → {slug: {state, pid, log_path, exit_code}}
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


PHASE_SCRIPTS: dict[str, str] = {
    "beamline_alignment": "scripts/bl-aligner-claude.sh",
    "sample_alignment": "scripts/sample-aligner-claude.sh",
    "collection": "scripts/data-collection-claude.sh",
    "planner": "scripts/planner-claude.sh",
}


@dataclass
class _Slot:
    proc: subprocess.Popen
    log_path: str
    log_file: object  # file handle
    started_at: float
    exit_code: Optional[int] = None
    finished_at: Optional[float] = None


_lock = threading.Lock()
_slots: dict[str, _Slot] = {}
# Last-known result per slug so the UI can render "complete"/"failed" tiles
# after a process exits.
_last_results: dict[str, dict] = {}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _logs_dir() -> Path:
    p = _project_root() / "logs"
    p.mkdir(exist_ok=True)
    return p


def _watch_exit(slug: str, slot: _Slot) -> None:
    rc = slot.proc.wait()
    slot.exit_code = rc
    slot.finished_at = time.time()
    try:
        slot.log_file.flush()
        slot.log_file.close()
    except Exception:
        pass
    with _lock:
        _last_results[slug] = {
            "exit_code": rc,
            "log_path": slot.log_path,
            "started_at": slot.started_at,
            "finished_at": slot.finished_at,
        }
        # Only clear the slot if it still points at this proc (avoid
        # racing a fresh start that re-used the slug).
        cur = _slots.get(slug)
        if cur is slot:
            _slots.pop(slug, None)
    logger.info("phase agent %s exited rc=%s log=%s", slug, rc, slot.log_path)


def start(slug: str) -> dict:
    """Spawn the phase agent script for `slug`. Returns a status dict.

    Raises ValueError if already running, or if the slug/script is unknown.
    """
    if slug not in PHASE_SCRIPTS:
        raise ValueError(f"unknown phase slug: {slug!r}")
    script = _project_root() / PHASE_SCRIPTS[slug]
    if not script.exists():
        raise ValueError(f"script missing: {script}")

    with _lock:
        if slug in _slots and _slots[slug].proc.poll() is None:
            raise ValueError(f"phase agent for {slug!r} already running")

        ts = time.strftime("%Y%m%d-%H%M%S")
        log_path = _logs_dir() / f"phase_{slug}_{ts}.log"
        log_file = open(log_path, "ab", buffering=0)
        proc = subprocess.Popen(
            ["bash", str(script)],
            cwd=str(_project_root()),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # so SIGTERM kills the whole subtree
        )
        slot = _Slot(
            proc=proc,
            log_path=str(log_path),
            log_file=log_file,
            started_at=time.time(),
        )
        _slots[slug] = slot

    threading.Thread(
        target=_watch_exit, args=(slug, slot), daemon=True,
    ).start()

    return {
        "slug": slug,
        "pid": proc.pid,
        "log_path": str(log_path),
        "started_at": slot.started_at,
    }


def kill(slug: str) -> dict:
    """Send SIGTERM to the running phase agent. Returns status dict."""
    with _lock:
        slot = _slots.get(slug)
    if slot is None or slot.proc.poll() is not None:
        raise ValueError(f"no phase agent running for {slug!r}")

    try:
        # killpg because we set start_new_session=True
        os.killpg(slot.proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except Exception as e:
        logger.warning("killpg failed for %s, falling back to terminate(): %s", slug, e)
        try:
            slot.proc.terminate()
        except Exception:
            pass
    return {"slug": slug, "killed": True, "pid": slot.proc.pid}


def status_all() -> dict:
    """Return {slug: {state, ...}} for every known phase."""
    out: dict[str, dict] = {}
    with _lock:
        for slug in PHASE_SCRIPTS:
            slot = _slots.get(slug)
            if slot is not None and slot.proc.poll() is None:
                out[slug] = {
                    "state": "running",
                    "pid": slot.proc.pid,
                    "log_path": slot.log_path,
                    "started_at": slot.started_at,
                }
            else:
                last = _last_results.get(slug)
                if last is None:
                    out[slug] = {"state": "idle"}
                else:
                    rc = last.get("exit_code")
                    state = "complete" if rc == 0 else "failed"
                    out[slug] = {
                        "state": state,
                        "exit_code": rc,
                        "log_path": last.get("log_path"),
                        "started_at": last.get("started_at"),
                        "finished_at": last.get("finished_at"),
                    }
    return out


def get_log_path(slug: str) -> Optional[str]:
    """Return the most recent log path for a slug (running or finished)."""
    with _lock:
        slot = _slots.get(slug)
        if slot is not None:
            return slot.log_path
        last = _last_results.get(slug)
        return last.get("log_path") if last else None
