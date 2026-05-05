"""`spec_cmd` — whitelisted command dispatcher for SPEC.

Single entry point for *every* SPEC interaction the agent can perform.
Implements the design from
`design_handoff_autonomous_beamline_agent/needed-tools-for-autonomy.md`:

  * A hard allowlist of commands (no free-form strings).
  * A phase gate (see spec/phase_allowlist.py).
  * `action_log` write *before* SPEC injection; result written after.
  * Read-only calls routed to `query_log` instead.

The dispatcher is synchronous: each call blocks until the SPEC prompt
returns (or the timeout fires). The FastAPI layer exposes a non-blocking
submit + poll variant on top of this, but internal callers (orchestrator,
smoke tests) can use this directly.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from beamline_tools.action_log.db import (
    finish_action,
    log_query,
    mark_action_started,
    start_action,
)
from beamline_tools.config import SPEC_MOCK, SPEC_TRANSPORT
from beamline_tools.spec_control import (
    phase_allowlist,
    sandbox_client,
    screen_client,
    tcp_client,
    transport,
)
from beamline_tools.spec_control.transport import DispatchResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transport router
# ---------------------------------------------------------------------------
# Selection happens here, at the dispatcher layer — not buried inside any
# transport module. Order of precedence:
#   1. SPEC_MOCK=1   → in-memory simulator (transport._MockScreen)
#   2. SPEC_TRANSPORT=tcp    → tcp_client (default)
#   3. SPEC_TRANSPORT=screen → screen_client (legacy fallback)


def dispatch(spec_string: str, *, timeout_s: float = 1800.0) -> DispatchResult:
    """Route a SPEC command to the active transport.

    When SPEC_MOCK=1 the sandbox is tried first; _MockScreen is the fallback
    if the sandbox API is unreachable.  When SPEC_MOCK=0, SPEC_TRANSPORT
    selects among sandbox / tcp / screen with no fallback.
    """
    if SPEC_MOCK:
        if sandbox_client.is_healthy():
            result = sandbox_client.dispatch(spec_string, timeout_s=timeout_s)
            # Fall back to _MockScreen only on API-level failures (transport
            # error, server error).  SPEC-level failures (non-zero exit,
            # macro timeout) are valid sandbox results — return them.
            err = result.error or ""
            api_failure = ("transport error" in err or "server error" in err)
            if not api_failure:
                return result
            logger.warning("sandbox transport failed, falling back to _MockScreen: %s",
                           result.error)
        started = time.time()
        output = transport._MockScreen.inject(spec_string)
        return DispatchResult(
            ok=True, output=output, prompt_seen=True,
            elapsed_s=time.time() - started,
        )
    if SPEC_TRANSPORT == "sandbox":
        return sandbox_client.dispatch(spec_string, timeout_s=timeout_s)
    if SPEC_TRANSPORT == "tcp":
        return tcp_client.dispatch(spec_string, timeout_s=timeout_s)
    if SPEC_TRANSPORT == "screen":
        return screen_client.dispatch(spec_string, timeout_s=timeout_s)
    raise ValueError(
        f"unknown SPEC_TRANSPORT={SPEC_TRANSPORT!r} (expected 'tcp', 'screen', or 'sandbox')"
    )


def abort_current() -> bool:
    """Route an abort to the active transport."""
    if SPEC_MOCK:
        logger.info("[mock] abort")
        transport.release(output=None, errored=False)
        return True
    if SPEC_TRANSPORT == "sandbox":
        return sandbox_client.abort_current()
    if SPEC_TRANSPORT == "tcp":
        return tcp_client.abort_current()
    if SPEC_TRANSPORT == "screen":
        return screen_client.abort_current()
    raise ValueError(
        f"unknown SPEC_TRANSPORT={SPEC_TRANSPORT!r} (expected 'tcp', 'screen', or 'sandbox')"
    )


# ---------------------------------------------------------------------------
# Command specs
# ---------------------------------------------------------------------------

@dataclass
class CommandSpec:
    name: str
    kind: str  # "read" | "action"
    to_spec: Callable[[list[str]], str]
    result_parser: Callable[[str, list[str]], Any] = field(
        default=lambda out, args: {"raw": out}
    )
    needs_motor_allow: bool = False
    motor_arg_index: int = 0
    timeout_s: float = 1800.0


def _args_join(args: list[str]) -> str:
    return " ".join(args)


# ---- Parsers -------------------------------------------------------------

def _parse_wa(out: str, _a) -> dict:
    positions: dict[str, float] = {}
    for line in out.splitlines():
        m = re.match(r"\s*([A-Za-z0-9_]+)\s*=\s*(-?\d+\.?\d*)", line)
        if m:
            try:
                positions[m.group(1)] = float(m.group(2))
            except ValueError:
                continue
    return {"positions": positions, "raw": out}


def _parse_single_float(out: str, _a) -> dict:
    for tok in out.split():
        try:
            return {"value": float(tok), "raw": out}
        except ValueError:
            continue
    return {"value": None, "raw": out}


def _parse_int(out: str, _a) -> dict:
    for tok in out.split():
        try:
            return {"value": int(tok), "raw": out}
        except ValueError:
            continue
    return {"value": None, "raw": out}


def _parse_ct(out: str, _a) -> dict:
    # e.g. "I0=1.2e5  I1=8.9e4  vortDT=3.7e3  I2=2.1e2"
    counters: dict[str, float] = {}
    for m in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(-?\d+\.?\d*(?:[eE][+-]?\d+)?)", out):
        try:
            counters[m.group(1)] = float(m.group(2))
        except ValueError:
            continue
    return {"counters": counters, "raw": out}


def _parse_beam_status(out: str, _a) -> dict:
    # Accept either Python-dict-like or k=v format.
    sp = re.search(r"spear_current[^\d-]*([\d.]+)", out)
    bl = re.search(r"bl_state[^A-Z]*([A-Z_]+)", out)
    gap = re.search(r"gap_owned[^\d]*(\d)", out)
    current = float(sp.group(1)) if sp else None
    bl_state = bl.group(1) if bl else None
    gap_owned = bool(int(gap.group(1))) if gap else None
    beam_good = (
        current is not None and current > 200 and
        bl_state == "OPEN" and gap_owned
    )
    reason = None
    if not beam_good:
        if current is not None and current <= 200:
            reason = f"SPEAR current low ({current} mA)"
        elif bl_state and bl_state != "OPEN":
            reason = f"beamline state is {bl_state}"
        elif gap_owned is False:
            reason = "gap not owned by BL15-2"
    return {
        "spear_current_ma": current,
        "beamline_state": bl_state,
        "gap_owned": gap_owned,
        "beam_good": beam_good,
        "reason": reason,
        "raw": out,
    }


# ---- Command registry ----------------------------------------------------

_READ: dict[str, CommandSpec] = {
    "wa": CommandSpec("wa", "read", lambda a: "wa", _parse_wa),
    "p_motor": CommandSpec(
        "p_motor", "read",
        lambda a: f"p A[{a[0]}]" if a else "wa",
        _parse_single_float,
    ),
    "get_S": CommandSpec("get_S", "read", lambda a: "p S", lambda o, a: {"raw": o}),
    "ct": CommandSpec(
        "ct", "read",
        lambda a: f"ct {a[0] if a else '0.5'}",
        _parse_ct,
    ),
    "fon": CommandSpec("fon", "read", lambda a: "fon", lambda o, a: {"raw": o}),
    "pwd": CommandSpec("pwd", "read", lambda a: "pwd", lambda o, a: {"raw": o, "cwd": o.strip()}),
    "scan_n": CommandSpec("scan_n", "read", lambda a: "p SCAN_N", _parse_int),
    "beam_status": CommandSpec(
        "beam_status", "read",
        lambda a: "p beam_status()",
        _parse_beam_status,
    ),
    "p_global": CommandSpec(
        "p_global", "read",
        lambda a: f"p {a[0]}" if a else "wa",
        _parse_single_float,
    ),
}

_ACTION: dict[str, CommandSpec] = {
    # Primitives
    "umv": CommandSpec(
        "umv", "action",
        lambda a: f"umv {a[0]} {a[1]}",
        lambda o, a: {"motor": a[0], "target": float(a[1]), "raw": o},
        needs_motor_allow=True, motor_arg_index=0, timeout_s=60,
    ),
    "umvr": CommandSpec(
        "umvr", "action",
        lambda a: f"umvr {a[0]} {a[1]}",
        lambda o, a: {"motor": a[0], "delta": float(a[1]), "raw": o},
        needs_motor_allow=True, motor_arg_index=0, timeout_s=60,
    ),
    "mv": CommandSpec(
        "mv", "action",
        lambda a: f"mv {a[0]} {a[1]}",
        lambda o, a: {"motor": a[0], "target": a[1], "raw": o},
        needs_motor_allow=True, motor_arg_index=0, timeout_s=30,
    ),
    "ascan": CommandSpec(
        "ascan", "action",
        lambda a: f"ascan {a[0]} {a[1]} {a[2]} {a[3]} {a[4]}",
        lambda o, a: {
            "motor": a[0], "start": float(a[1]), "end": float(a[2]),
            "npoints": int(a[3]), "count_time": float(a[4]), "raw": o,
        },
        needs_motor_allow=True, motor_arg_index=0, timeout_s=1800,
    ),
    "dscan": CommandSpec(
        "dscan", "action",
        lambda a: f"dscan {a[0]} {a[1]} {a[2]} {a[3]} {a[4]}",
        lambda o, a: {
            "motor": a[0], "delta_start": float(a[1]), "delta_end": float(a[2]),
            "npoints": int(a[3]), "count_time": float(a[4]), "raw": o,
        },
        needs_motor_allow=True, motor_arg_index=0, timeout_s=1800,
    ),
    "cen": CommandSpec("cen", "action", lambda a: "cen", lambda o, a: {"raw": o}, timeout_s=30),
    "peak": CommandSpec("peak", "action", lambda a: "peak", lambda o, a: {"raw": o}, timeout_s=30),

    # Shutter
    "shutter": CommandSpec(
        "shutter", "action",
        lambda a: _render_shutter(a),
        lambda o, a: {"command": a[0], "raw": o},
        timeout_s=15,
    ),

    # Energy / gap
    "mv_energy": CommandSpec(
        "mv_energy", "action",
        lambda a: f"umv energy {a[0]}",
        lambda o, a: {"target_ev": float(a[0]), "raw": o},
        timeout_s=120,
    ),
    "gaprequest": CommandSpec(
        "gaprequest", "action",
        lambda a: "gaprequest",
        lambda o, a: {"raw": o, "granted": "grant" in o.lower()},
        timeout_s=900,
    ),

    # Elements / scans / files
    "select_element": CommandSpec(
        "select_element", "action",
        lambda a: f"select_element(\"{a[0]}\")",
        lambda o, a: {"element": a[0], "raw": o},
        timeout_s=120,
    ),
    "xas": CommandSpec(
        "xas", "action",
        lambda a: _render_xas(a),
        lambda o, a: {"element": a[0], "count_time": float(a[1]), "n_reps": int(a[2]), "raw": o},
        timeout_s=36000,
    ),
    "emiss_scan": CommandSpec(
        "emiss_scan", "action",
        lambda a: _render_emiss(a),
        lambda o, a: {
            "element": a[0], "count_time": float(a[1]), "n_reps": int(a[2]),
            "emission_ev": float(a[3]), "filter": int(a[4]), "raw": o,
        },
        timeout_s=36000,
    ),
    "safely_remove_filters": CommandSpec(
        "safely_remove_filters", "action",
        lambda a: "safely_remove_filters",
        lambda o, a: {"raw": o}, timeout_s=30,
    ),
    "set_i0_gain": CommandSpec(
        "set_i0_gain", "action",
        lambda a: f'set_i0_gain("{a[0]}")',
        lambda o, a: {"gain": a[0], "raw": o}, timeout_s=15,
    ),
    "set_i1_gain": CommandSpec(
        "set_i1_gain", "action",
        lambda a: f'set_i1_gain("{a[0]}")',
        lambda o, a: {"gain": a[0], "raw": o}, timeout_s=15,
    ),
    "set_i2_gain": CommandSpec(
        "set_i2_gain", "action",
        lambda a: f'set_i2_gain("{a[0]}")',
        lambda o, a: {"gain": a[0], "raw": o}, timeout_s=15,
    ),
    "set_vortex_roi": CommandSpec(
        "set_vortex_roi", "action",
        lambda a: _render_vortex_roi(a),
        lambda o, a: {"args": a, "raw": o}, timeout_s=15,
    ),
    "newfile": CommandSpec(
        "newfile", "action",
        lambda a: f"newfile {a[0]}",
        lambda o, a: {"filename": a[0], "raw": o}, timeout_s=15,
    ),
    "run_shortcut": CommandSpec(
        "run_shortcut", "action",
        lambda a: a[0],
        lambda o, a: {"name": a[0], "raw": o}, timeout_s=900,
    ),
    "abort": CommandSpec(
        "abort", "action",
        lambda a: "__ABORT__",
        lambda o, a: {"aborted": True, "raw": o}, timeout_s=5,
    ),

    # High-level procedurals
    "align_beamline": CommandSpec(
        "align_beamline", "action",
        lambda a: _render_align_beamline(a),
        lambda o, a: {"raw": o}, timeout_s=3600,
    ),
    "align_xes": CommandSpec(
        "align_xes", "action",
        lambda a: _render_align_xes(a),
        lambda o, a: {"crystals": a[0], "raw": o}, timeout_s=3600,
    ),
    "auto_sample_align": CommandSpec(
        "auto_sample_align", "action",
        lambda a: "auto_sample_align",
        lambda o, a: {"raw": o}, timeout_s=7200,
    ),
    "run_collection": CommandSpec(
        "run_collection", "action",
        lambda a: "run_collection",
        lambda o, a: {"raw": o}, timeout_s=86400,  # hours to days
    ),
    "peak_mono_pitch": CommandSpec(
        "peak_mono_pitch", "action",
        lambda a: "peak_mono_pitch",
        lambda o, a: {"raw": o}, timeout_s=600,
    ),
    "calibrate_mono": CommandSpec(
        "calibrate_mono", "action",
        lambda a: f"calibrate_mono {a[0]}",
        lambda o, a: {"tabulated_ev": float(a[0]), "raw": o}, timeout_s=180,
    ),
}


# ---- Renderers for polyvalent commands ----------------------------------

def _render_shutter(a: list[str]) -> str:
    if not a:
        raise ValueError("shutter requires a subcommand")
    cmd = a[0]
    if cmd not in ("fsopen", "fsclose", "fson", "fsoff"):
        raise ValueError(f"invalid shutter command: {cmd}")
    if cmd == "fson" and len(a) > 1:
        return f"fson {a[1]}"
    return cmd


def _render_xas(a: list[str]) -> str:
    # element_xas <count_time> <reps> [<emiss>]
    base = f"{a[0]}_xas {a[1]} {a[2]}"
    if len(a) > 3:
        return f"{base} {a[3]}"
    return base


def _render_emiss(a: list[str]) -> str:
    # element_cee <count_time> <reps> <emission_ev> <filter>
    return f"{a[0]}_cee {a[1]} {a[2]} {a[3]} {a[4]}"


def _render_vortex_roi(a: list[str]) -> str:
    if a[0] == "auto":
        channel = a[1] if len(a) > 1 else "3"
        return f"vortex_roi auto {channel}"
    # explicit: channel lo hi
    return f"vortex_roi {a[0]} {a[1]} {a[2]}"


def _render_align_beamline(a: list[str]) -> str:
    energy = a[0] if len(a) > 0 else "0"
    xtal_chg = a[1] if len(a) > 1 else "0"
    fine_x = a[2] if len(a) > 2 else "0"
    fine_z = a[3] if len(a) > 3 else "0"
    return f"align_the_beamline({energy}, 0, {xtal_chg}, {fine_x}, {fine_z})"


def _render_align_xes(a: list[str]) -> str:
    crystals = a[0] if a else "1234567"
    en_xes = a[1] if len(a) > 1 else "0"
    en_mono = a[2] if len(a) > 2 else "0"
    return f'run_spec_align("{crystals}", {en_xes}, {en_mono})'


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_PHASE_STATE: dict[str, Any] = {"phase": phase_allowlist.PHASE_SETUP, "experiment_id": None}


def set_phase(phase: str, experiment_id: str | None = None) -> None:
    if phase not in phase_allowlist.ALL_PHASES:
        raise ValueError(f"unknown phase: {phase}")
    _PHASE_STATE["phase"] = phase
    if experiment_id:
        _PHASE_STATE["experiment_id"] = experiment_id


def get_phase() -> str:
    return _PHASE_STATE["phase"]


def get_experiment_id() -> Optional[str]:
    return _PHASE_STATE.get("experiment_id")


def call(
    command: str,
    args: list[str] | tuple[str, ...] | None,
    justification: str = "",
    *,
    agent: str = "llm",
    experiment_id: str | None = None,
    phase_override: str | None = None,
) -> dict:
    """Synchronously dispatch a spec_cmd call.

    Returns a dict: {"ok": bool, "action_id"?: str, "result"?: ..., "error"?: str, "kind": "read"|"action"}.
    """
    args_list = list(args or [])
    phase = phase_override or get_phase()
    exp_id = experiment_id or get_experiment_id()

    spec = _READ.get(command) or _ACTION.get(command)
    if spec is None:
        return {"ok": False, "kind": "unknown", "error": f"unknown command: {command}"}

    # Phase gate
    allowed, reason = phase_allowlist.command_allowed(phase, command)
    if not allowed:
        return {"ok": False, "kind": spec.kind, "error": reason}

    # Motor allow
    if spec.needs_motor_allow and len(args_list) > spec.motor_arg_index:
        motor = args_list[spec.motor_arg_index]
        if not phase_allowlist.motor_allowed(phase, motor):
            return {
                "ok": False, "kind": spec.kind,
                "error": f"motor '{motor}' not on allowlist for phase '{phase}'",
            }

    # Render the SPEC string *before* logging (so we log exactly what we'll send).
    try:
        spec_string = spec.to_spec(args_list)
    except Exception as e:
        return {"ok": False, "kind": spec.kind, "error": f"failed to render command: {e}"}

    # ----- READ path: query_log only, no busy check ---------------------
    if spec.kind == "read":
        t0 = time.time()
        if not transport.reserve(action_id="query", command=command):
            log_query(command, args_list, None, phase=phase, experiment_id=exp_id,
                      error_message="SPEC busy")
            return {"ok": False, "kind": "read", "error": "SPEC is busy"}
        try:
            dr = dispatch(spec_string, timeout_s=spec.timeout_s)
        finally:
            transport.release(output=None, errored=False)
        latency_ms = int((time.time() - t0) * 1000)
        if not dr.ok:
            log_query(command, args_list, None, phase=phase, experiment_id=exp_id,
                      error_message=dr.error, latency_ms=latency_ms)
            return {"ok": False, "kind": "read", "error": dr.error}
        parsed = spec.result_parser(dr.output, args_list)
        log_query(command, args_list, parsed, phase=phase, experiment_id=exp_id,
                  latency_ms=latency_ms)
        return {"ok": True, "kind": "read", "result": parsed}

    # ----- ACTION path: action_log BEFORE dispatch ----------------------
    if not justification.strip():
        return {"ok": False, "kind": "action", "error": "justification is required for action commands"}

    row = start_action(
        command=command,
        args=args_list,
        justification=justification,
        phase=phase,
        spec_string=spec_string,
        experiment_id=exp_id,
        agent=agent,
    )

    # Special-case abort — send Ctrl-C instead of injecting a literal string.
    if command == "abort":
        mark_action_started(row.id)
        ok = abort_current()
        finish_action(row.id, success=ok, result={"aborted": ok})
        return {"ok": ok, "kind": "action", "action_id": row.id}

    if not transport.reserve(action_id=row.id, command=command):
        finish_action(row.id, success=False, error_message="SPEC is busy")
        return {"ok": False, "kind": "action", "action_id": row.id, "error": "SPEC is busy"}

    mark_action_started(row.id)
    try:
        dr: DispatchResult = dispatch(spec_string, timeout_s=spec.timeout_s)
    finally:
        transport.release(output=None, errored=False)

    if not dr.ok:
        finish_action(row.id, success=False, error_message=dr.error,
                      screen_output=dr.output or "")
        return {"ok": False, "kind": "action", "action_id": row.id, "error": dr.error}

    try:
        parsed = spec.result_parser(dr.output, args_list)
    except Exception as e:
        parsed = {"raw": dr.output, "parse_error": str(e)}

    scan_number = None
    if command in ("ascan", "dscan", "xas", "emiss_scan", "run_shortcut"):
        # Best-effort scan-number capture
        m = re.search(r"(?:scan[_ ]?n|scan)\s*=?\s*#?(\d+)", dr.output, re.IGNORECASE)
        if m:
            try:
                scan_number = int(m.group(1))
            except ValueError:
                pass
    parsed["elapsed_s"] = dr.elapsed_s
    finish_action(
        row.id, success=True, result=parsed,
        screen_output=dr.output, scan_number=scan_number,
    )
    return {
        "ok": True, "kind": "action", "action_id": row.id,
        "result": parsed, "elapsed_s": dr.elapsed_s,
    }


# ---------------------------------------------------------------------------
# Introspection for tests / UI
# ---------------------------------------------------------------------------

def known_commands() -> dict[str, list[str]]:
    return {
        "read": sorted(_READ.keys()),
        "action": sorted(_ACTION.keys()),
    }
