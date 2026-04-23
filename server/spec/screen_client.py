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
    SPEC_TRANSPORT,
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

def _sim_engine():
    """Return the simulation engine module if active, else None."""
    try:
        from simulation import engine as eng  # type: ignore
    except Exception:
        return None
    return eng if eng.is_active() else None


class _MockScreen:
    """In-memory stand-in that synthesizes believable SPEC output.

    Not a full SPEC model — just enough to exercise the dispatcher,
    action_log, orchestrator, and UI without a live beamline. When the
    `simulation` package has been bootstrapped, scan-producing commands
    are routed through `simulation.engine` so a real (mock) SPEC file
    appears on disk and `get_latest_scan` etc. surface the new data.
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
    def _filename_active(cls) -> str:
        eng = _sim_engine()
        return eng.current_file() if eng else cls._filename

    @classmethod
    def _set_filename(cls, name: str) -> None:
        cls._filename = name
        eng = _sim_engine()
        if eng:
            eng.set_current_file(name)

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
            tokens = cmd.split()
            try:
                motor = tokens[1]
                lo = float(tokens[2]); hi = float(tokens[3])
                npts = int(tokens[4]); ct = float(tokens[5])
                if low.startswith("dscan "):
                    cur = cls._positions.get(motor, 0.0)
                    lo, hi = cur + lo, cur + hi
            except (IndexError, ValueError):
                cls._scan_n += 1
                return f"Scan #{cls._scan_n} complete. File={cls._filename}"
            eng = _sim_engine()
            if eng:
                meta = eng.append_ascan(motor, lo, hi, npts, ct,
                                        positions=dict(cls._positions))
                cls._scan_n = meta["scan_number"]
                return (f"Scan #{meta['scan_number']} complete. "
                        f"File={meta['file_name']}  motor={motor}")
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
                cls._set_filename(tokens[1])
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
            alias = low.split()[0]
            eng = _sim_engine()
            if eng:
                meta = eng.append_alias_scan(alias, positions=dict(cls._positions))
                cls._scan_n = meta["scan_number"]
                return (f"{alias} scan complete. scan_n={meta['scan_number']} "
                        f"file={meta['file_name']}")
            cls._scan_n += 1
            return f"{low} scan complete. scan_n={cls._scan_n}"
        # XAS / emission scans rendered as `<elem>_xas` / `<elem>_cee`
        if "_xas " in low or low.endswith("_xas"):
            tokens = cmd.split()
            elem = tokens[0].split("_xas")[0]
            try:
                ct = float(tokens[1]) if len(tokens) > 1 else 0.5
                reps = int(tokens[2]) if len(tokens) > 2 else 1
            except ValueError:
                ct, reps = 0.5, 1
            eng = _sim_engine()
            if eng:
                last = None
                for _ in range(max(reps, 1)):
                    last = eng.append_xas_scan(elem, count_time=ct,
                                               positions=dict(cls._positions))
                    cls._scan_n = last["scan_number"]
                return (f"{elem}_xas complete. reps={reps} "
                        f"last_scan={last['scan_number']} file={last['file_name']}")
            cls._scan_n += reps
            return f"{elem}_xas complete. reps={reps} scan_n={cls._scan_n}"
        if "_cee " in low or low.endswith("_cee"):
            tokens = cmd.split()
            elem = tokens[0].split("_cee")[0]
            try:
                ct = float(tokens[1]) if len(tokens) > 1 else 0.5
                reps = int(tokens[2]) if len(tokens) > 2 else 1
            except ValueError:
                ct, reps = 0.5, 1
            eng = _sim_engine()
            if eng:
                last = None
                for _ in range(max(reps, 1)):
                    last = eng.append_emiss_scan(elem, count_time=ct,
                                                 positions=dict(cls._positions))
                    cls._scan_n = last["scan_number"]
                return (f"{elem}_cee complete. reps={reps} "
                        f"last_scan={last['scan_number']} file={last['file_name']}")
            cls._scan_n += reps
            return f"{elem}_cee complete. reps={reps} scan_n={cls._scan_n}"
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

    Routes to the TCP server-mode client by default; set
    SPEC_TRANSPORT=screen to force the legacy screen-stuffing path.
    """
    if SPEC_TRANSPORT == "tcp":
        # Lazy import to keep tcp_client's `from spec.screen_client ...`
        # out of the module-load cycle.
        from spec import tcp_client
        return tcp_client.dispatch(spec_string, timeout_s=timeout_s)

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
    """Abort the currently running SPEC command.

    With SPEC_TRANSPORT=tcp (default) this sends an SV_ABORT packet to
    the server — equivalent to ^C at the server keyboard. With
    SPEC_TRANSPORT=screen, stuffs a literal ^C into the screen session.
    """
    if SPEC_TRANSPORT == "tcp":
        from spec import tcp_client
        return tcp_client.abort_current()

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
