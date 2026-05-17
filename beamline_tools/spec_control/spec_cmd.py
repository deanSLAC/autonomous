"""`spec_cmd` — primitive whitelisted command dispatcher for SPEC.

Renders a registered command + args to its SPEC wire string, reserves
the transport, dispatches, parses, releases. That's it. Knows nothing
about phases, experiments, or the action_log.

The phase / experiment / audit-log concerns are layered on top by
`beamline_tools.audited_call.audited_call`, which is what tool handlers
normally use. Use `spec_cmd.call` directly only when you genuinely want
the primitive (e.g. a transport-level health check that should not
appear in the action_log).

  * Hard allowlist of commands (no free-form strings).
  * Read-only and action commands share a single `call()` entry point;
    `command_kind()` reports the registered kind.

Permission enforcement (which commands and motors each agent role may
invoke) lives at the CLI layer in `scripts/beamtimehero` — see
`AGENT_ROLES`, `agent_motor_allowed`, and the per-role argparse branch.

The dispatcher is synchronous: each call blocks until the SPEC prompt
returns (or the timeout fires).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from beamline_tools.config import SPEC_MOCK, SPEC_TRANSPORT
from beamline_tools.spec_control import (
    sandbox_client,
    screen_client,
    tcp_client,
    transport,
)
from beamline_tools.spec_control.transport import DispatchResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safety switches — re-read from disk on every call so flipping the file
# takes effect immediately without restarting the process.
# ---------------------------------------------------------------------------

_SAFETY_SWITCHES_PATH = Path(__file__).resolve().parent.parent / "safety_switches.json"


_KIND_TO_SWITCH = {"read": "spec_read_enabled", "action": "spec_write_enabled"}


def _safety_check(kind: str) -> str | None:
    """Return an error string if the safety switch for *kind* is off, else None."""
    key = _KIND_TO_SWITCH.get(kind)
    if key is None:
        return None
    try:
        with open(_SAFETY_SWITCHES_PATH) as f:
            switches = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None  # fail-open: missing/corrupt file doesn't block
    if switches.get(key, True) is False:
        label = "read" if kind == "read" else "write"
        return (
            f"SAFETY SWITCH: spec {label} commands are disabled "
            f"(set {key}=true in {_SAFETY_SWITCHES_PATH.name} to re-enable)"
        )
    return None


_JUSTIFICATION_MAX = 200


def _spec_print_prefix(justification: str) -> str:
    """Render a SPEC `print` statement that echoes the justification.

    Returns "" when the justification is empty so callers can prepend
    unconditionally.
    """
    s = (justification or "").strip()
    if not s:
        return ""
    s = " ".join(s.split())
    if len(s) > _JUSTIFICATION_MAX:
        s = s[: _JUSTIFICATION_MAX - 1] + "…"
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'print "BeamtimeHero: {s}"; '


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
            sim_string = f"check_beam_off; {spec_string}"
            result = sandbox_client.dispatch(sim_string, timeout_s=timeout_s)
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
            transport="mock",
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
    timeout_s: float = 1800.0


def _args_join(args: list[str]) -> str:
    return " ".join(args)


# ---- Parsers -------------------------------------------------------------

def _parse_wa(out: str, _a) -> dict:
    positions: dict[str, float] = {}
    # Try name=value format (_MockScreen fallback: "  name = value")
    for line in out.splitlines():
        m = re.match(r"\s*([A-Za-z0-9_]+)\s*=\s*(-?\d+\.?\d*)", line)
        if m:
            try:
                positions[m.group(1)] = float(m.group(2))
            except ValueError:
                continue
    if positions:
        return {"positions": positions, "raw": out}
    # Columnar format (real SPEC wa): repeating 4-line blocks separated
    # by blank lines.  Each block: names, names (repeated), user vals,
    # dial vals.  We extract user positions (3rd line of each block).
    data_lines = []
    for line in out.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("current"):
            continue
        data_lines.append(stripped)
    for i in range(0, len(data_lines) - 3, 4):
        names = data_lines[i].split()
        user_vals = data_lines[i + 2].split()
        for name, val_str in zip(names, user_vals):
            try:
                positions[name] = float(val_str)
            except ValueError:
                continue
    return {"positions": positions, "raw": out}


def _parse_wm(out: str, args: list[str]) -> dict:
    # wm output has a "User" section with High/Current/Low lines.
    # Extract the Current value under "User".
    in_user = False
    for line in out.splitlines():
        stripped = line.strip()
        if stripped == "User":
            in_user = True
            continue
        if stripped == "Dial":
            in_user = False
            continue
        if in_user and stripped.startswith("Current"):
            for tok in stripped.split()[1:]:
                try:
                    return {"value": float(tok), "raw": out}
                except ValueError:
                    continue
    return {"value": None, "raw": out}


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
    counters: dict[str, float] = {}
    # Try name=value format first (standard SPEC show_cnts / _MockScreen)
    for m in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(-?\d+\.?\d*(?:[eE][+-]?\d+)?)", out):
        try:
            counters[m.group(1)] = float(m.group(2))
        except ValueError:
            continue
    if counters:
        return {"counters": counters, "raw": out}
    # Tabular fallback: a name line followed by a value line
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    for i in range(len(lines) - 1):
        names = lines[i].split()
        vals = lines[i + 1].split()
        if len(names) < 2 or len(vals) < 2 or len(names) != len(vals):
            continue
        if not all(re.match(r"[A-Za-z_]", n) for n in names):
            continue
        paired: dict[str, float] = {}
        for n, v in zip(names, vals):
            try:
                paired[n] = float(v)
            except ValueError:
                break
        else:
            if paired:
                counters = paired
                break
    return {"counters": counters, "raw": out}


def _parse_anchor(out: str, _a) -> dict:
    # Macro prints lines like:
    #   energy: 8979
    #   (m1vert: 0.95)
    #   m1vert1: 0.836
    #   crystal: B
    #   SPEAR steering: -0.42
    # …plus optional WARNING blocks if SPEAR drifted or the crystal changed.
    def _num(label: str):
        m = re.search(rf"\b{label}\s*:\s*([\-+\d.eE]+)", out)
        if not m:
            return None
        try:
            return float(m.group(1))
        except ValueError:
            return None

    crystal_m = re.search(r"\bcrystal\s*:\s*(\S+)", out)
    return {
        "energy":          _num("energy"),
        "m1vert":          _num("m1vert"),
        "m1vert1":         _num("m1vert1"),
        "m1vert2":         _num("m1vert2"),
        "Tz":              _num("Tz"),
        "Tz1":             _num("Tz1"),
        "Tz2":             _num("Tz2"),
        "crystal":         crystal_m.group(1) if crystal_m else None,
        "spear_steering":  _num("SPEAR steering"),
        "spear_drift":     "SPEAR has apparently moved" in out,
        "crystal_changed": "CRYSTAL SET HAS CHANGED" in out,
        "raw": out,
    }


def _parse_herfd_energy(out: str, _a) -> dict:
    # The macro prints "Suggested new emission value is <float>" once the
    # external fitter has converged. Anything else means the fit failed
    # or the scan was unusable; surface that with energy_ev=None and
    # the raw output so the agent can decide what to do.
    m = re.search(r"Suggested new emission value is\s*([-+]?\d+\.?\d*)", out)
    energy = float(m.group(1)) if m else None
    return {"emission_ev": energy, "raw": out}


def _parse_show_elements(out: str, _a) -> dict:
    current = None
    elements = []
    for m in re.finditer(
        r"(\d+)\.\s+(\S+)\s+\(incident=([\d.]+)\s*eV,\s*emission=([\d.]+)\s*eV\)"
        r"(\s*<<\s*CURRENT)?",
        out,
    ):
        name = m.group(2)
        entry = {
            "name": name,
            "incident_ev": float(m.group(3)),
            "emission_ev": float(m.group(4)),
        }
        elements.append(entry)
        if m.group(5):
            current = name
    return {"current_element": current, "elements": elements, "raw": out}


def _parse_wbeamsize(out: str, _a) -> dict:
    size_m = re.search(r"Beam size \(X, Z\):\s*([\d.]+)\s*,\s*([\d.]+)", out)
    mode_m = re.search(r"Beam mode \(X, Z\):\s*(\S+)\s*,\s*(\S+)", out)
    h_mm = float(size_m.group(1)) if size_m else None
    v_mm = float(size_m.group(2)) if size_m else None

    # Persist the measured FWHM (mm → µm) on the active experiment row so
    # the dashboard's Beam field can switch from the configured big/focused
    # mode strings to the actual numbers once beamline_alignment has run.
    # Best-effort: a missing experiment / DB error must not break the read.
    if h_mm is not None or v_mm is not None:
        try:
            from orchestration.runtime_state import get_experiment_id as _xid
            xid = _xid()
            if xid:
                from orchestration.plan_store.session import record_measured_beam_size
                record_measured_beam_size(
                    xid,
                    h_mm * 1000.0 if h_mm is not None else None,
                    v_mm * 1000.0 if v_mm is not None else None,
                )
        except Exception:
            pass

    return {
        "horizontal_fwhm_mm": h_mm,
        "vertical_fwhm_mm": v_mm,
        "horizontal_mode": mode_m.group(1) if mode_m else None,
        "vertical_mode": mode_m.group(2) if mode_m else None,
        "raw": out,
    }


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
        lambda a: f"wm {a[0]}" if a else "wa",
        _parse_wm,
    ),
    "get_S": CommandSpec("get_S", "read", lambda a: "p S", lambda o, a: {"raw": o}),
    "ct": CommandSpec(
        "ct", "read",
        lambda a: f"ct {a[0] if a else '1'}",
        _parse_ct,
    ),
    "fon": CommandSpec("fon", "read", lambda a: "fon", lambda o, a: {"raw": o}),
    "p_datafile": CommandSpec("p_datafile", "read", lambda a: "p DATAFILE", lambda o, a: {"datafile": o.strip(), "raw": o}),
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
    "show_elements": CommandSpec(
        "show_elements", "read",
        lambda a: "show_elements",
        _parse_show_elements,
    ),
    "p_element": CommandSpec(
        "p_element", "read",
        lambda a: "p ELEMENT",
        lambda o, a: {"element": o.strip(), "raw": o},
    ),
    "plotselected": CommandSpec(
        "plotselected", "read",
        lambda a: "p cnt_mne(DET)",
        lambda o, a: {"counter": o.strip(), "raw": o},
    ),
    "wbeamsize": CommandSpec(
        "wbeamsize", "read",
        lambda a: "wbeamsize",
        _parse_wbeamsize,
    ),
    "get_anchor": CommandSpec(
        "get_anchor", "read",
        lambda a: "get_anchor",
        _parse_anchor,
    ),
}

_ACTION: dict[str, CommandSpec] = {
    # Primitives
    "umv": CommandSpec(
        "umv", "action",
        lambda a: f"umv {a[0]} {a[1]}",
        lambda o, a: {"motor": a[0], "target": float(a[1]), "raw": o},
        timeout_s=60,
    ),
    "umvr": CommandSpec(
        "umvr", "action",
        lambda a: f"umvr {a[0]} {a[1]}",
        lambda o, a: {"motor": a[0], "delta": float(a[1]), "raw": o},
        timeout_s=60,
    ),
    "mv": CommandSpec(
        "mv", "action",
        lambda a: f"mv {a[0]} {a[1]}",
        lambda o, a: {"motor": a[0], "target": a[1], "raw": o},
        timeout_s=30,
    ),
    "ascan": CommandSpec(
        "ascan", "action",
        lambda a: f"ascan {a[0]} {a[1]} {a[2]} {a[3]} {a[4]}",
        lambda o, a: {
            "motor": a[0], "start": float(a[1]), "end": float(a[2]),
            "npoints": int(a[3]), "count_time": float(a[4]), "raw": o,
        },
        timeout_s=1800,
    ),
    "dscan": CommandSpec(
        "dscan", "action",
        lambda a: f"dscan {a[0]} {a[1]} {a[2]} {a[3]} {a[4]}",
        lambda o, a: {
            "motor": a[0], "delta_start": float(a[1]), "delta_end": float(a[2]),
            "npoints": int(a[3]), "count_time": float(a[4]), "raw": o,
        },
        timeout_s=1800,
    ),
    "d2scan": CommandSpec(
        "d2scan", "action",
        lambda a: f"d2scan {a[0]} {a[1]} {a[2]} {a[3]} {a[4]} {a[5]} {a[6]} {a[7]}",
        lambda o, a: {
            "motor1": a[0], "delta_lo1": float(a[1]), "delta_hi1": float(a[2]),
            "motor2": a[3], "delta_lo2": float(a[4]), "delta_hi2": float(a[5]),
            "npoints": int(a[6]), "count_time": float(a[7]), "raw": o,
        },
        timeout_s=1800,
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
    "m2_stripe": CommandSpec(
        "m2_stripe", "action",
        lambda a: f"m2_stripe({a[0]})",
        lambda o, a: {"energy_ev": float(a[0]), "raw": o},
        timeout_s=60,
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
    "run_xas": CommandSpec(
        "run_xas", "action",
        lambda a: _render_run_xas(a),
        lambda o, a: {
            "count_time": float(a[0]), "n_reps": int(a[1]),
            "emission_ev": float(a[2]), "filter": int(a[3]), "raw": o,
        },
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
    "plotselect": CommandSpec(
        "plotselect", "action",
        lambda a: f"plotselect {a[0]}",
        lambda o, a: {"counter": a[0], "raw": o}, timeout_s=5,
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
    "get_HERFD_energy": CommandSpec(
        "get_HERFD_energy", "action",
        lambda a: f"get_HERFD_energy {a[0]}" if a else "get_HERFD_energy",
        _parse_herfd_energy,
        timeout_s=120,
    ),

    # Beam-diagnostic tool moves (sample-position diagnostic, alignment only)
    "mvpinhole": CommandSpec(
        "mvpinhole", "action",
        lambda a: "mvpinhole",
        lambda o, a: {"raw": o}, timeout_s=60,
    ),
    "mvplastic": CommandSpec(
        "mvplastic", "action",
        lambda a: "mvplastic",
        lambda o, a: {"raw": o}, timeout_s=60,
    ),
    "mvknifeclear": CommandSpec(
        "mvknifeclear", "action",
        lambda a: "mvknifeclear",
        lambda o, a: {"raw": o}, timeout_s=60,
    ),
    "mvknifewayout": CommandSpec(
        "mvknifewayout", "action",
        lambda a: "mvknifewayout",
        lambda o, a: {"raw": o}, timeout_s=120,
    ),

    # Long-running diagnostic procedures
    "measure_beam_size": CommandSpec(
        "measure_beam_size", "action",
        lambda a: f"measure_beam_size {a[0]} {a[1]}",
        lambda o, a: {"mode_x": int(a[0]), "mode_z": int(a[1]), "raw": o},
        timeout_s=600,
    ),
    "zero_pinhole": CommandSpec(
        "zero_pinhole", "action",
        lambda a: "zero_pinhole",
        lambda o, a: {"raw": o}, timeout_s=600,
    ),

    # KB-mirror bender presets and encoder recalibrations
    "smallbeam": CommandSpec(
        "smallbeam", "action",
        lambda a: "smallbeam",
        lambda o, a: {"raw": o, "mode": "small"}, timeout_s=60,
    ),
    "bigbeam": CommandSpec(
        "bigbeam", "action",
        lambda a: "bigbeam",
        lambda o, a: {"raw": o, "mode": "big"}, timeout_s=60,
    ),
    "xtalalign": CommandSpec(
        "xtalalign", "action",
        lambda a: "xtalalign",
        lambda o, a: {"raw": o}, timeout_s=120,
    ),
    "reset_gap": CommandSpec(
        "reset_gap", "action",
        lambda a: "reset_gap",
        lambda o, a: {"raw": o}, timeout_s=180,
    ),

    # Energy tracking — anchor + on/off
    "set_anchor": CommandSpec(
        "set_anchor", "action",
        lambda a: "set_anchor",
        lambda o, a: {"raw": o}, timeout_s=30,
    ),
    "tracking": CommandSpec(
        "tracking", "action",
        lambda a: f"tracking {a[0]}",
        lambda o, a: {"enabled": int(a[0]) == 1, "raw": o}, timeout_s=15,
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


def _render_run_xas(a: list[str]) -> str:
    # run_xas <cntSec> <nbrScan> <emission> <nbrFilter>
    # Element is set by select_element; SPEC dispatches to <El>_xas.
    return f"run_xas {a[0]} {a[1]} {a[2]} {a[3]}"


def _render_emiss(a: list[str]) -> str:
    # element_cee <count_time> <reps> <emission_ev> <filter>
    return f"{a[0]}_cee {a[1]} {a[2]} {a[3]} {a[4]}"


def _render_vortex_roi(a: list[str]) -> str:
    if a[0] == "auto":
        channel = a[1] if len(a) > 1 else "1"
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

def command_kind(command: str) -> Optional[str]:
    """Return 'read'|'action' for a registered command, or None if unknown."""
    if command in _READ:
        return "read"
    if command in _ACTION:
        return "action"
    return None


def render(command: str, args: list[str] | tuple[str, ...] | None) -> str:
    """Render a registered command + args to its SPEC wire string.

    Raises KeyError for unknown commands; the spec-side renderer may
    raise other exceptions for bad argument shapes (e.g. shutter without
    a subcommand).
    """
    spec = _READ.get(command) or _ACTION.get(command)
    if spec is None:
        raise KeyError(f"unknown command: {command}")
    return spec.to_spec(list(args or []))


def call(
    command: str,
    args: list[str] | tuple[str, ...] | None,
    justification: str = "",
    *,
    action_id: str | None = None,
) -> dict:
    """Primitive SPEC dispatch — no audit, no phase, no experiment context.

    Renders the command, checks the SPEC-level safety switch, reserves
    the transport, dispatches, parses, releases. The audit-log /
    phase / experiment concerns are layered on by
    `beamline_tools.audited_call.audited_call`, which is what tool
    handlers normally use.

    `justification` is forwarded as a SPEC-side `print` prefix so a
    human watching the SPEC console sees why the command ran; this is
    purely informational and not validated here. Action handlers
    requiring a justification enforce that at the wrapper layer.

    `action_id` is passed to `transport.reserve` for busy-state
    tracking; supply a stable id (e.g. the action_log row id) when
    available, otherwise a 'primitive' sentinel is used.

    Returns: {"ok": bool, "kind": "read"|"action"|"unknown",
              "result"?: dict, "output"?: str, "elapsed_s"?: float,
              "error"?: str}
    """
    args_list = list(args or [])

    spec = _READ.get(command) or _ACTION.get(command)
    if spec is None:
        return {"ok": False, "kind": "unknown", "error": f"unknown command: {command}"}

    # Safety switch — checked on every call by re-reading the file.
    # `abort` always bypasses: stopping a runaway scan must work even
    # when spec_write_enabled is off (in fact, especially then).
    if command != "abort":
        safety_err = _safety_check(spec.kind)
        if safety_err:
            return {"ok": False, "kind": spec.kind, "error": safety_err}

    # Render the SPEC string before reserving so a render failure
    # doesn't leave the transport marked busy.
    try:
        spec_string = spec.to_spec(args_list)
    except Exception as e:
        return {"ok": False, "kind": spec.kind, "error": f"failed to render command: {e}"}

    reserve_id = action_id or "primitive"

    # ----- READ path -----
    if spec.kind == "read":
        if not transport.reserve(action_id=reserve_id, command=command):
            return {"ok": False, "kind": "read", "error": "SPEC is busy"}
        try:
            dr = dispatch(spec_string, timeout_s=spec.timeout_s)
        finally:
            transport.release(output=None, errored=False)
        if not dr.ok:
            return {"ok": False, "kind": "read", "error": dr.error, "output": dr.output}
        parsed = spec.result_parser(dr.output, args_list)
        return {"ok": True, "kind": "read", "result": parsed, "output": dr.output}

    # ----- ACTION path -----
    # Special-case abort — send Ctrl-C instead of injecting a literal string.
    if command == "abort":
        ok = abort_current()
        return {
            "ok": ok, "kind": "action",
            "result": {"aborted": ok},
        }

    if not transport.reserve(action_id=reserve_id, command=command):
        return {"ok": False, "kind": "action", "error": "SPEC is busy"}

    wire_string = _spec_print_prefix(justification) + spec_string
    try:
        dr: DispatchResult = dispatch(wire_string, timeout_s=spec.timeout_s)
    finally:
        transport.release(output=None, errored=False)

    if not dr.ok:
        return {
            "ok": False, "kind": "action",
            "error": dr.error, "output": dr.output or "",
        }

    try:
        parsed = spec.result_parser(dr.output, args_list)
    except Exception as e:
        parsed = {"raw": dr.output, "parse_error": str(e)}

    parsed["elapsed_s"] = dr.elapsed_s
    if dr.reply is not None:
        parsed["_reply"] = dr.reply
    if dr.transport:
        parsed["_transport"] = dr.transport
    return {
        "ok": True, "kind": "action",
        "result": parsed, "output": dr.output,
        "elapsed_s": dr.elapsed_s,
    }


# ---------------------------------------------------------------------------
# Introspection for tests / UI
# ---------------------------------------------------------------------------

def known_commands() -> dict[str, list[str]]:
    return {
        "read": sorted(_READ.keys()),
        "action": sorted(_ACTION.keys()),
    }
