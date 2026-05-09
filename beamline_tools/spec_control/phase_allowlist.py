"""Per-phase motor + command allowlists.

Authoritative source: `design_handoff_autonomous_beamline_agent/needed-tools-for-autonomy.md`.

`spec_cmd` consults this module *before* dispatch. A command that is
valid syntactically but targets a motor not on the current phase's
allowlist is rejected with a structured error — the action_log row is
still written (so the refused attempt is auditable).
"""

from __future__ import annotations

from typing import Set

# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

PHASE_SETUP = "setup"
PHASE_BL_ALIGN = "beamline_alignment"
PHASE_XES_ALIGN = "xes_alignment"
PHASE_SAMPLE_ALIGN = "sample_alignment"
PHASE_COLLECTION = "collection"
PHASE_COMPLETE = "complete"
PHASE_UNRESTRICTED = "unrestricted"

ALL_PHASES = [
    PHASE_SETUP,
    PHASE_BL_ALIGN,
    PHASE_XES_ALIGN,
    PHASE_SAMPLE_ALIGN,
    PHASE_COLLECTION,
    PHASE_COMPLETE,
]

# All phase identifiers accepted by `set_phase`. `unrestricted` is a bypass
# mode (no allowlist enforcement) and is intentionally not in the ordered
# workflow sequence above, so transition_phase / PHASE_ORDER ignore it.
VALID_PHASES = set(ALL_PHASES) | {PHASE_UNRESTRICTED}

# Forward sequence used to judge forward vs. backward transitions.
PHASE_ORDER = {name: i for i, name in enumerate(ALL_PHASES)}


# ---------------------------------------------------------------------------
# Motor allowlists (from the spec, verbatim)
# ---------------------------------------------------------------------------

_BL_ALIGN_MOTORS: Set[str] = {
    "energy", "mono", "crystal", "gap",
    "m1vert", "m1pitch", "m2vert", "m2horz",
    "pitcha", "pitchb",
    "monvgap", "monhgap", "monvtra", "monhtra",
    "s1vgap", "s1hgap", "s1vtran", "s1htran",
    "Bx", "Bz", "Tz", "Tp",
    "Sx", "Sy", "Sz", "Sr",
    "filter",
}

_XES_ALIGN_MOTORS: Set[str] = {
    "emiss", "Az", "Dz",
    "Ax1", "Ax2", "Ax3", "Ax4", "Ax5", "Ax6", "Ax7",
    "c1y", "c2y", "c3y", "c4y", "c5y", "c6y", "c7y",
    "c1p", "c2p", "c3p", "c4p", "c5p", "c6p", "c7p",
    "mono", "energy",
}

_SAMPLE_ALIGN_MOTORS: Set[str] = {
    "Sx", "Sy", "Sz", "Sr", "energy", "emiss", "filter",
}

_COLLECTION_MOTORS: Set[str] = _SAMPLE_ALIGN_MOTORS


_ALL_MOTORS: Set[str] = _BL_ALIGN_MOTORS | _XES_ALIGN_MOTORS | _SAMPLE_ALIGN_MOTORS

MOTOR_ALLOWLIST = {
    PHASE_BL_ALIGN: _BL_ALIGN_MOTORS,
    PHASE_XES_ALIGN: _XES_ALIGN_MOTORS,
    PHASE_SAMPLE_ALIGN: _SAMPLE_ALIGN_MOTORS,
    PHASE_COLLECTION: _COLLECTION_MOTORS,
    # Setup has no motor ops yet; complete is a no-op phase.
    PHASE_SETUP: set(),
    PHASE_COMPLETE: set(),
    PHASE_UNRESTRICTED: _ALL_MOTORS,
}


# ---------------------------------------------------------------------------
# High-level procedural macros — phase restrictions
# ---------------------------------------------------------------------------

PROCEDURAL_PHASE = {
    "align_beamline": {PHASE_BL_ALIGN},
    "align_xes": {PHASE_XES_ALIGN},
    "auto_sample_align": {PHASE_SAMPLE_ALIGN},
    "run_collection": {PHASE_COLLECTION},
    "peak_mono_pitch": {PHASE_BL_ALIGN},
    "calibrate_mono": {PHASE_BL_ALIGN},
    "select_element": {PHASE_SAMPLE_ALIGN, PHASE_COLLECTION},
    "run_xas": {PHASE_COLLECTION},
    "emiss_scan": {PHASE_COLLECTION},
    "run_shortcut": {PHASE_BL_ALIGN},
    # Beam-diagnostic tool moves (sample-position diagnostic, alignment only)
    "mvpinhole": {PHASE_BL_ALIGN},
    "mvplastic": {PHASE_BL_ALIGN, PHASE_XES_ALIGN},
    "mvknifeclear": {PHASE_BL_ALIGN},
    "mvknifewayout": {PHASE_BL_ALIGN},
    "measure_beam_size": {PHASE_BL_ALIGN},
    "zero_pinhole": {PHASE_BL_ALIGN},
    # KB-mirror bender presets and encoder recalibrations
    "smallbeam": {PHASE_BL_ALIGN},
    "bigbeam": {PHASE_BL_ALIGN},
    "xtalalign": {PHASE_BL_ALIGN},
    "reset_gap": {PHASE_BL_ALIGN},
    # M2 stripe selection (energy-dependent: Si below ~6.2 keV, Rh above)
    "m2_stripe": {PHASE_BL_ALIGN},
    # Energy tracking
    "set_anchor": {PHASE_BL_ALIGN},
    "tracking": {PHASE_BL_ALIGN, PHASE_XES_ALIGN, PHASE_SAMPLE_ALIGN, PHASE_COLLECTION},
    # Sample-alignment helpers
    "get_HERFD_energy": {PHASE_SAMPLE_ALIGN, PHASE_COLLECTION},
}

# "All" tier — any phase except PHASE_COMPLETE.
_ANY_RUNNING = set(ALL_PHASES) - {PHASE_COMPLETE}

PROCEDURAL_ANY_PHASE = {
    "umv", "umvr", "mv", "ascan", "dscan", "d2scan",
    "cen", "peak", "shutter", "mv_energy", "gaprequest",
    "safely_remove_filters", "set_i0_gain", "set_i1_gain",
    "set_i2_gain", "set_vortex_roi", "newfile", "abort", "plotselect",
    # Read-only:
    "wa", "p_motor", "get_S", "ct", "fon", "p_datafile", "pwd", "scan_n",
    "beam_status", "p_global", "get_anchor", "wbeamsize", "show_elements", "p_element",
    "plotselected",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def motor_allowed(phase: str, motor: str) -> bool:
    allow = MOTOR_ALLOWLIST.get(phase, set())
    return motor in allow


def command_allowed(phase: str, command: str) -> tuple[bool, str]:
    """Return (allowed, reason). reason is '' on success."""
    if phase == PHASE_UNRESTRICTED:
        return True, ""
    if phase == PHASE_COMPLETE:
        return False, f"experiment is in '{PHASE_COMPLETE}' — no more actions"
    if command in PROCEDURAL_ANY_PHASE:
        return True, ""
    allowed_phases = PROCEDURAL_PHASE.get(command)
    if allowed_phases is None:
        # Unknown command — let the dispatcher reject it elsewhere.
        return False, f"unknown command: {command}"
    if phase in allowed_phases:
        return True, ""
    pretty = ", ".join(sorted(allowed_phases))
    return False, f"command '{command}' is only allowed in phase(s): {pretty} (current phase: {phase})"


def direction(prev: str, nxt: str) -> str:
    """Classify a phase transition as 'forward' | 'backward' | 'same'."""
    if prev == nxt:
        return "same"
    a = PHASE_ORDER.get(prev, -1)
    b = PHASE_ORDER.get(nxt, -1)
    if b > a:
        return "forward"
    return "backward"


def backward_steps(prev: str, nxt: str) -> int:
    return max(0, PHASE_ORDER.get(prev, 0) - PHASE_ORDER.get(nxt, 0))
