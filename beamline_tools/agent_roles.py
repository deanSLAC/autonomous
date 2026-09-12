"""Per-agent-role CLI surfaces for the autonomous beamtimehero CLI.

Each role — beamline aligner, sample aligner, data collector, sample
surveyor — gets its own top-level branch of the `beamtimehero` CLI, and
that branch *is* the enforcement. The agent's Claude permission line
restricts its Bash invocations to the branch, the branch carries only the
mutating tools the role may call, and the motor allow-list is enforced
inside the branch's executor. There is no global state an agent can flip
to widen its scope.

This file used to state that policy as plain dicts and leave three other
places to transcribe it: `scripts/beamtimehero` assembled the argparse
branch and re-derived "is this a write tool?" from whether the schema
required a `justification`; it then walked argparse internals to stamp
the role onto the leaves it could find; and each agent's
`.claude/agents/*.md` front matter restated the motor list in prose. The
three drifted, which is the ordinary outcome of writing one fact down
three times:

  * the pasted motor lists in the prompt files did not match these sets;
  * the `_agent_role` stamp reached four of the nine trees under a
    branch, so leaves on the other five were never motor-checked;
  * the `justification` heuristic classified four audited DB uploads as
    harmless, so each role's write set named tools the filter ignored.

Now the surface is *declared*, once, here.
`beamtimehero_cli.agent_surface.build_surface()` generates the argparse
branch, the restricted dispatch table, the motor-guarded executor, the
`Bash(...)` permission pattern, the prompt fragment and a checked-in
manifest from this declaration — see `scripts/render_agent_surfaces.py`.

Read the fields as:

  branches     All nine canonical trees, which is what the hand-built
               branch already carried. A role's scope is not expressed by
               hiding read tools; it is expressed by `write_tools` and
               `motors`.
  write_tools  Tool *names* this role may mutate with. Every other
               mutating tool is dropped from the branch entirely rather
               than carried-and-refused: a tool an agent can see in
               `--help` is a tool it will try, and advertising moves it
               may not make trains the model to ignore its own scope.
               "Mutating" is the declared `mutates` flag in
               `tool_catalog/lineage.py`, not an inference from the
               argument schema.
  motors       Enforced as a before-hook on the surface's executor, so a
               harness that calls the executor directly is guarded too —
               which the old CLI-level check was not.
  phase        Recorded on the manifest and in the prompt fragment. Not
               gating; phase enforcement lives in
               `beamtimehero_cli.spec_control.phases`.

Phase constants are imported from upstream; only the autonomy-specific
role policy lives here.
"""

from __future__ import annotations

from typing import Set

from beamtimehero_cli.agent_surface import AgentSurface
from beamtimehero_cli.spec_control.phases import (
    PHASE_BL_ALIGN,
    PHASE_COLLECTION,
    PHASE_SAMPLE_ALIGN,
)

# ---------------------------------------------------------------------------
# Motor sets.
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
# The nine canonical trees. Shared by every role: see `branches` above.
# ---------------------------------------------------------------------------

_ALL_BRANCHES: tuple[str, ...] = (
    "tool", "db", "spec-read", "spec-write", "spec-file",
    "s3df", "slack", "xrs", "exafs",
)


def _surface(
    name: str,
    *,
    phase: str,
    motors: Set[str],
    write_tools: Set[str],
) -> AgentSurface:
    """One role's surface, with the shared fields filled in.

    `description` is the branch's `--help` line. It is worded exactly as
    the hand-built branch worded it, so the migration reads as a no-op to
    anyone running `beamtimehero --help`.
    """
    return AgentSurface(
        name=name,
        description=(
            f"Agent scope: {name} (phase={phase}). "
            "Filters spec-write tools and validates motor args."
        ),
        layout="nested",
        branches=_ALL_BRANCHES,
        write_tools=frozenset(write_tools),
        motors=frozenset(motors),
        include_ref=True,
        phase=phase,
    )


SURFACES: dict[str, AgentSurface] = {
    "blaligner": _surface(
        "blaligner",
        phase=PHASE_BL_ALIGN,
        motors=_BL_ALIGN_MOTORS,
        write_tools={
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
            "record_alignment_flux",
        },
    ),
    "samplealigner": _surface(
        "samplealigner",
        phase=PHASE_SAMPLE_ALIGN,
        motors=_SAMPLE_ALIGN_MOTORS,
        write_tools={
            "select_element", "move_motor", "move_motor_relative",
            "run_motor_scan", "run_motor_scan_relative", "run_diagonal_scan",
            "fit_emission_peak", "mv_energy", "shutter", "set_filter",
            "safely_remove_filters", "set_gain", "set_vortex_roi",
            "open_data_file", "plotselect", "tracking", "abort_current_scan",
            "upload_sample_alignment_results",
        },
    ),
    "collector": _surface(
        "collector",
        phase=PHASE_COLLECTION,
        motors=_COLLECTION_MOTORS,
        write_tools={
            "select_element", "run_xas", "run_emiss_scan", "run_collection",
            "fit_emission_peak", "move_motor", "move_motor_relative",
            "run_motor_scan", "run_motor_scan_relative", "mv_energy",
            "shutter", "set_filter", "safely_remove_filters", "set_gain",
            "set_vortex_roi", "open_data_file", "plotselect", "tracking",
            "abort_current_scan", "record_completed_scan",
        },
    ),
    "surveyor": _surface(
        "surveyor",
        phase=PHASE_COLLECTION,
        motors=_COLLECTION_MOTORS,
        write_tools={
            "select_element", "run_xas", "run_emiss_scan",
            "fit_emission_peak", "move_motor", "move_motor_relative",
            "run_motor_scan", "run_motor_scan_relative", "mv_energy",
            "shutter", "set_filter", "safely_remove_filters", "set_gain",
            "set_vortex_roi", "open_data_file", "plotselect", "tracking",
            "abort_current_scan",
            "upload_sample_survey_results",
        },
    ),
}


__all__ = ["SURFACES"]
