"""Thin wrapper around GNU screen for SPEC sessions.

Extends the beamtimehero pattern with a *dispatch + prompt-poll* cycle:

  1. inject via `screen -S <session> -X stuff "<cmd>\\n"`
  2. periodically capture the screen buffer (`screen -X hardcopy`)
  3. watch for the `N.SPEC>` prompt on the last non-empty line
  4. return captured output between inject and prompt-return

If `SPEC_MOCK=1` in the env the client short-circuits to an in-memory
simulator so the server can run (and the agent loop can be exercised)
on machines without a live SPEC daemon.
"""

from __future__ import annotations

import itertools
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from config import (
    SPEC_SCREEN_NAME,
    SPEC_POLL_INTERVAL_S,
    SPEC_PROMPT_REGEX,
    SPEC_MOCK,
)

logger = logging.getLogger(__name__)

_PROMPT_RE = re.compile(SPEC_PROMPT_REGEX)


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

STATE_IDLE = "idle"
STATE_BUSY = "busy"
STATE_ERRORED = "errored"


@dataclass
class DispatchResult:
    """Outcome of a single injected SPEC command."""
    ok: bool
    output: str
    prompt_seen: bool
    elapsed_s: float
    error: Optional[str] = None


@dataclass
class _SpecState:
    state: str = STATE_IDLE
    last_cmd: Optional[str] = None
    last_action_id: Optional[str] = None
    started_at: Optional[float] = None
    last_output: Optional[str] = None
    lock: threading.RLock = field(default_factory=threading.RLock)


_state = _SpecState()


# ---------------------------------------------------------------------------
# Mock simulator
# ---------------------------------------------------------------------------

class _MockScreen:
    """In-memory stand-in that synthesizes believable SPEC output.

    Not a full SPEC model — just enough to exercise the dispatcher,
    action_log, orchestrator, and UI without a live beamline.
    """

    _scan_counter = itertools.count(1)
    _positions = {
        "m1vert": 1.93, "m1pitch": 0.0, "m2vert": 0.0, "m2horz": 0.0,
        "pitcha": 0.0, "pitchb": 0.0, "energy": 7100.0, "emiss": 6400.0,
        "Sx": 0.0, "Sy": 0.0, "Sz": 10.0, "Sr": 0.0, "filter": 0,
        "mono": 7100.0, "gap": 38.0, "crystal": 0,
        "Az": 0.0, "Dz": 0.0, "Bx": 0.0, "Bz": 0.0, "Tz": 0.0, "Tp": 0.0,
    }
    _scan_n = 1000
    _filename = "mock.01"
    _logfile = "mock.log"

    @classmethod
    def inject(cls, cmd: str) -> str:
        cmd = cmd.strip()
        low = cmd.lower()
        if low == "wa":
            parts = ["Current motor positions:"]
            for m, v in cls._positions.items():
                parts.append(f"  {m:>10s} = {v:.4f}")
            return "\n".join(parts)
        if low == "fon":
            return f"data = {cls._filename} / log = {cls._logfile}"
        if low == "pwd":
            return "/data/fifteen/mock"
        if low.startswith("p scan_n"):
            return str(cls._scan_n)
        if low.startswith("p get_beam_status"):
            return "{'spear_current': 485.2, 'bl_state': 'OPEN', 'gap_owned': 1}"
        if low.startswith("p a["):
            motor = cmd.split("[")[1].split("]")[0]
            return f"{cls._positions.get(motor, 0.0)}"
        if low.startswith("p "):
            rest = cmd[2:].strip()
            return f"{cls._positions.get(rest, 0.0)}"
        if low.startswith("p s"):
            return "[1.2e5, 8.9e4, 3.7e3, 2.1e2]  # I0, I1, vortDT, I2"
        if low.startswith("ct "):
            return "I0=1.2e5  I1=8.9e4  vortDT=3.7e3  I2=2.1e2"
        if low.startswith(("umv ", "mv ", "umvr ")):
            tokens = cmd.split()
            # umv m1vert 1.93 -> record new position
            if len(tokens) >= 3:
                motor = tokens[1]
                try:
                    pos = float(tokens[2])
                    cls._positions[motor] = pos
                except ValueError:
                    pass
            return "Move complete."
        if low.startswith(("ascan ", "dscan ")):
            cls._scan_n += 1
            return f"Scan #{cls._scan_n} complete. File={cls._filename}"
        if low.startswith("cen") or low.startswith("peak"):
            return "Moved scanned motor to feature."
        if low.startswith("align_the_beamline"):
            time.sleep(0.2)  # simulate long-running macro
            cls._positions["m1vert"] = 1.93
            cls._positions["m2horz"] = 0.12
            return (
                "align_the_beamline complete.\n"
                "final_energy_ev=7100 beam_size_h=0.35 beam_size_v=0.12 anchor=saved"
            )
        if low.startswith("run_spec_align") or low.startswith("xes_align"):
            return "run_spec_align complete. XES_EN_OFFSET=-0.42"
        if low.startswith("auto_sample_align"):
            return "auto_sample_align complete. samples_found=6"
        if low.startswith("run_collection"):
            return "run_collection complete. samples_completed=6 files=6"
        if low.startswith("select_element"):
            return "select_element complete."
        if low.startswith("calibrate_mono"):
            return "calibrate_mono complete. offset=-0.11"
        if low.startswith("peak_mono_pitch"):
            return "peak_mono_pitch complete. gain=1.18"
        if low.startswith("gaprequest"):
            return "gap granted."
        if low.startswith("newfile"):
            tokens = cmd.split()
            if len(tokens) >= 2:
                cls._filename = tokens[1]
            return f"new file: {cls._filename}"
        if low.startswith(("fson", "fsoff", "fsopen", "fsclose")):
            return f"shutter: {low}"
        if low.startswith(("set_i0_gain", "set_i1_gain", "set_i2_gain")):
            return "gain set."
        if low.startswith("vortex_roi"):
            return "ROI set."
        if low.startswith("safely_remove_filters"):
            cls._positions["filter"] = 0
            return "filters removed."
        if low.startswith(("vvv", "hhh", "m1m1", "m2m2", "ggg", "bzbz", "bxbx",
                           "dmm", "beamx", "beamz", "cm1m1", "cm2m2")):
            cls._scan_n += 1
            return f"{low} scan complete. scan_n={cls._scan_n}"
        return f"ok: {cmd}"


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------

def get_state() -> dict:
    with _state.lock:
        return {
            "state": _state.state,
            "command": _state.last_cmd,
            "action_id": _state.last_action_id,
            "started_at": _state.started_at,
            "elapsed_s": (time.time() - _state.started_at) if _state.started_at else None,
            "last_output": _state.last_output,
        }


def reserve(action_id: str, command: str) -> bool:
    """Try to mark SPEC busy; return False if already busy."""
    with _state.lock:
        if _state.state == STATE_BUSY:
            return False
        _state.state = STATE_BUSY
        _state.last_cmd = command
        _state.last_action_id = action_id
        _state.started_at = time.time()
        _state.last_output = None
        return True


def release(output: str | None, errored: bool) -> None:
    with _state.lock:
        _state.state = STATE_ERRORED if errored else STATE_IDLE
        _state.last_output = output


def dispatch(
    spec_string: str,
    *,
    timeout_s: float = 1800.0,
    settle_sleep_s: float = 0.5,
) -> DispatchResult:
    """Inject a SPEC string and wait for the `SPEC>` prompt to return.

    Returns a DispatchResult describing the captured output. Caller is
    responsible for having already `reserve()`d the SPEC state.
    """
    started = time.time()

    if SPEC_MOCK:
        # Simulate the screen round-trip + prompt-return timing.
        output = _MockScreen.inject(spec_string)
        elapsed = time.time() - started
        return DispatchResult(ok=True, output=output, prompt_seen=True, elapsed_s=elapsed)

    # Check the screen session exists
    result = subprocess.run(["screen", "-list"], capture_output=True, text=True)
    if SPEC_SCREEN_NAME not in result.stdout:
        return DispatchResult(
            ok=False, output="", prompt_seen=False,
            elapsed_s=time.time() - started,
            error=f"screen session '{SPEC_SCREEN_NAME}' not running",
        )

    # Inject the command
    try:
        subprocess.run(
            ["screen", "-S", SPEC_SCREEN_NAME, "-X", "stuff", f"{spec_string}\n"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        return DispatchResult(
            ok=False, output="", prompt_seen=False,
            elapsed_s=time.time() - started,
            error=f"screen stuff failed: {e}",
        )

    # Short settle before first capture (many motor moves return <1s)
    time.sleep(settle_sleep_s)

    # Poll until prompt returns or timeout
    tmpfile = tempfile.NamedTemporaryFile(delete=False, suffix=".screen", mode="w")
    tmpfile.close()
    try:
        prompt_seen = False
        last_capture = ""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                subprocess.run(
                    ["screen", "-S", SPEC_SCREEN_NAME, "-X", "hardcopy", tmpfile.name],
                    capture_output=True, text=True, check=True, timeout=10,
                )
                with open(tmpfile.name, "r", errors="replace") as f:
                    last_capture = f.read()
            except Exception as e:  # capture failure is non-fatal; keep trying
                logger.warning("hardcopy failed: %s", e)

            if _has_prompt(last_capture):
                prompt_seen = True
                break
            time.sleep(SPEC_POLL_INTERVAL_S)

        return DispatchResult(
            ok=prompt_seen,
            output=last_capture,
            prompt_seen=prompt_seen,
            elapsed_s=time.time() - started,
            error=None if prompt_seen else "timeout waiting for SPEC> prompt",
        )
    finally:
        try:
            os.unlink(tmpfile.name)
        except OSError:
            pass


def _has_prompt(buf: str) -> bool:
    for line in reversed([l.rstrip() for l in buf.splitlines()]):
        if not line:
            continue
        if _PROMPT_RE.match(line):
            return True
        # first non-empty line is not a prompt → still running
        return False
    return False


def abort_current() -> bool:
    """Send Ctrl-C to the SPEC screen (mock or real)."""
    if SPEC_MOCK:
        logger.info("[mock] abort")
        release(output=None, errored=False)
        return True
    try:
        subprocess.run(
            ["screen", "-S", SPEC_SCREEN_NAME, "-X", "stuff", "\x03"],
            capture_output=True, text=True, check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error("abort failed: %s", e)
        return False
