"""Phase identifiers and per-agent-role allowlists.

The workflow has six labelled phases. The current phase is a simple
property of the experiment, persisted in `ExperimentPlan.phase` and
cached in `orchestration.runtime_state`. There is no precondition gate,
no forward/backward direction logic, no Slack-approved backward
transitions — those layers were removed. The operator (or whatever
spawned the phase agent) is trusted; agents enforce their own readiness
checks.

Permission enforcement for SPEC tool calls does *not* live here. It is
handled at the CLI layer in `scripts/beamtimehero`: each agent role has
its own argparse branch that filters spec-write tools (via
`spec_write_tools`) and validates motor arguments (via
`agent_motor_allowed`). The agent's Claude permission line restricts
its Bash invocations to that branch, so there is no global state it
can flip to escape its scope.

What lives here:
  * Phase constants + ordering (display + validation), consumed by the
    UI, the CLI, and the plan store.
  * `AGENT_ROLES`: the per-role motor allowlist and spec-write tool
    allowlist consulted by the CLI's argparse build and per-leaf motor
    check.
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

ALL_PHASES = [
    PHASE_SETUP,
    PHASE_BL_ALIGN,
    PHASE_XES_ALIGN,
    PHASE_SAMPLE_ALIGN,
    PHASE_COLLECTION,
    PHASE_COMPLETE,
]

# All phase identifiers accepted by `set_phase`.
VALID_PHASES = set(ALL_PHASES)

# Forward sequence used to judge forward vs. backward transitions.
PHASE_ORDER = {name: i for i, name in enumerate(ALL_PHASES)}


# ---------------------------------------------------------------------------
# Motor sets — referenced by AGENT_ROLES below.
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

_SAMPLE_ALIGN_MOTORS: Set[str] = {
    "Sx", "Sy", "Sz", "Sr", "energy", "emiss", "filter",
}

_COLLECTION_MOTORS: Set[str] = _SAMPLE_ALIGN_MOTORS


# ---------------------------------------------------------------------------
# Agent roles — enforced at the beamtimehero CLI level.
#
# Each role maps to (a) the phase it is associated with (recorded on
# action-log rows; not used for gating), (b) the motor allowlist the
# agent may target, (c) the spec-write tools the agent may invoke. The
# CLI's `_run_tool_leaf` checks the motor allowlist before dispatch; the
# agent branch's argparse `choices` enforces the spec-write tool list at
# parse time.
# ---------------------------------------------------------------------------

AGENT_ROLES: dict[str, dict] = {
    "blaligner": {
        "phase": PHASE_BL_ALIGN,
        "motors": _BL_ALIGN_MOTORS,
        "spec_write_tools": frozenset({
            "align_beamline", "peak_mono_pitch", "calibrate_mono",
            "select_element", "move_motor", "move_motor_relative",
            "run_motor_scan", "run_motor_scan_relative", "run_diagonal_scan",
            "fit_emission_peak", "mv_energy", "shutter", "set_filter",
            "safely_remove_filters", "set_gain", "set_vortex_roi",
            "open_data_file", "plotselect", "run_align_shortcut",
            "post_scan_move", "mv_pinhole", "mv_plastic", "mv_knife_clear",
            "mv_knife_out", "measure_beam_size", "zero_pinhole",
            "small_beam", "big_beam", "xtal_align", "reset_gap",
            "set_m2_stripe", "set_anchor", "tracking",
            "request_gap_ownership", "abort_current_scan",
        }),
    },
    "samplealigner": {
        "phase": PHASE_SAMPLE_ALIGN,
        "motors": _SAMPLE_ALIGN_MOTORS,
        "spec_write_tools": frozenset({
            "select_element", "move_motor", "move_motor_relative",
            "run_motor_scan", "run_motor_scan_relative", "run_diagonal_scan",
            "fit_emission_peak", "mv_energy", "shutter", "set_filter",
            "safely_remove_filters", "set_gain", "set_vortex_roi",
            "open_data_file", "plotselect", "tracking", "abort_current_scan",
            "upload_sample_alignment_results",
        }),
    },
    "collector": {
        "phase": PHASE_COLLECTION,
        "motors": _COLLECTION_MOTORS,
        "spec_write_tools": frozenset({
            "select_element", "run_xas", "run_emiss_scan", "run_collection",
            "fit_emission_peak", "move_motor", "move_motor_relative",
            "run_motor_scan", "run_motor_scan_relative", "mv_energy",
            "shutter", "set_filter", "safely_remove_filters", "set_gain",
            "set_vortex_roi", "open_data_file", "plotselect", "tracking",
            "abort_current_scan", "record_completed_scan",
        }),
    },
    "surveyor": {
        "phase": PHASE_COLLECTION,
        "motors": _COLLECTION_MOTORS,
        "spec_write_tools": frozenset({
            "select_element", "run_xas", "run_emiss_scan",
            "fit_emission_peak", "move_motor", "move_motor_relative",
            "run_motor_scan", "run_motor_scan_relative", "mv_energy",
            "shutter", "set_filter", "safely_remove_filters", "set_gain",
            "set_vortex_roi", "open_data_file", "plotselect", "tracking",
            "abort_current_scan",
            "upload_sample_survey_results",
        }),
    },
}


def agent_motor_allowed(role: str, motor: str) -> bool:
    """Return True if `motor` is on `role`'s motor allowlist.

    Unknown roles return False (no implicit fall-through).
    """
    role_def = AGENT_ROLES.get(role)
    if role_def is None:
        return False
    return motor in role_def["motors"]


def agent_tool_allowed(role: str, tool_name: str) -> bool:
    """Return True if `tool_name` is in `role`'s spec-write allowlist.

    Only consulted for spec-write tools. ref/tool/db/spec-read/steering
    subtrees are unfiltered at the agent-branch level.
    """
    role_def = AGENT_ROLES.get(role)
    if role_def is None:
        return False
    return tool_name in role_def["spec_write_tools"]


