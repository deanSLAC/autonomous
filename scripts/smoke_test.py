"""End-to-end smoke test for the autonomous beamline agent.

Runs in SPEC_MOCK mode (no real SPEC required). Walks through the phase
state machine exercising: spec_cmd dispatch, action_log writes, phase
transitions with preconditions, pause-for-human intervention resolution,
and plan/budget tracking.

Run from the repo root:

    PYTHONPATH=server SPEC_MOCK=1 AUTONOMOUS_DB_PATH=data/smoke.db \
        python scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("SPEC_MOCK", "1")
# Use a fresh in-repo DB so the test is reproducible.
if "AUTONOMOUS_DB_PATH" not in os.environ:
    td = Path(__file__).resolve().parent.parent / "data" / "smoke.db"
    td.parent.mkdir(exist_ok=True)
    if td.exists():
        td.unlink()
    os.environ["AUTONOMOUS_DB_PATH"] = str(td)
# Two sqlite files after the three-package split. The smoke test uses the
# same file path for both engines — the ActionLog / QueryLog schema lives
# in one table space and the orchestration tables in another; since they
# no longer share a FK, coexistence in one file is just a convenience.
os.environ.setdefault("BEAMLINE_TOOLS_DB_PATH", os.environ["AUTONOMOUS_DB_PATH"])
os.environ.setdefault("ORCHESTRATION_DB_PATH", os.environ["AUTONOMOUS_DB_PATH"])

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from orchestration.plan_store import init_db  # noqa: E402
from orchestration.plan_store.session import (  # noqa: E402
    create_experiment,
    create_experiment_element,
    create_sample_holder,
    create_sample_position,
)
from orchestration.plan_store.client import (  # noqa: E402
    get_experiment_plan,
)
from orchestration.planner import planner  # noqa: E402
from orchestration.planner.phase import PreconditionChecker, transition_phase  # noqa: E402
from orchestration.planner.staff_guidance import coordinator  # noqa: E402
from beamline_tools.spec import phase_allowlist, spec_cmd  # noqa: E402
from beamline_tools.action_log.db import recent_actions  # noqa: E402


def banner(label: str) -> None:
    print(f"\n{'=' * 12} {label} {'=' * 12}")


def assert_true(cond: bool, label: str) -> None:
    if cond:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}")
        raise SystemExit(1)


async def run() -> None:
    banner("init db")
    init_db()
    print(f"  db: {os.environ['AUTONOMOUS_DB_PATH']}")

    banner("create experiment + element + sample holder")
    exp = create_experiment(
        name="smoke-test-run", experimenter="smoketest",
        mono_crystal="A", beam_size_h="focused", beam_size_v="focused",
        sample_env="ambient",
    )
    create_experiment_element(
        experiment_id=exp.id, element_symbol="Fe", edge="K",
        incident_energy_eV=7300, emission_energy_eV=6400,
        crystal_type=0, crystal_hkl="6 4 2", row_radius=1000,
        n_crystals=3, vortex_channel=1, priority=0,
    )
    holder = create_sample_holder(
        experiment_id=exp.id, name="smoke-holder", n_samples=2, holder_type="flat",
    )
    for i, name in enumerate(["sample_a", "sample_b"], 1):
        create_sample_position(
            experiment_id=exp.id, sample_holder_id=holder.id,
            sample_number=i, sample_name=name, element_symbol="Fe",
            sx_lo=0, sx_hi=2, sy_lo=0, sy_hi=2, sz_lo=10, sz_hi=12,
            sx_del=0.1, sy_del=0.1, sz_del=0.05,
            total_spots=1, enabled=True, do_xas=True, xas_reps=3,
        )
    spec_cmd.set_phase(phase_allowlist.PHASE_SETUP, experiment_id=exp.id)
    assert_true(spec_cmd.get_experiment_id() == exp.id, "spec_cmd tracks experiment id")

    banner("build plan")
    plan = planner.build_initial_plan(exp.id, beamtime_hours=6.0)
    snap = planner.snapshot(exp.id)
    assert_true(snap.samples_total == 2, "two samples in plan")
    assert_true(snap.beamtime_total_hours == 6.0, "beamtime budget stored")

    banner("phase: setup -> beamline_alignment")
    checker = PreconditionChecker()
    checker.record("experiment_id", exp.id)
    checker.record("beam_good", True)
    checker.record("n_samples_configured", snap.samples_total)
    r = await transition_phase(exp.id, phase_allowlist.PHASE_BL_ALIGN,
                               "beginning alignment", checker)
    assert_true(r.allowed, "setup -> beamline_alignment allowed")
    assert_true(spec_cmd.get_phase() == phase_allowlist.PHASE_BL_ALIGN, "phase updated")

    banner("spec_cmd: read (wa) — allowed any phase")
    w = spec_cmd.call("wa", [], justification="")
    assert_true(w.get("ok") and "positions" in w["result"], "wa returned parsed positions")

    banner("spec_cmd: action without justification rejected")
    bad = spec_cmd.call("umv", ["m1vert", "1.93"], justification="")
    assert_true(not bad.get("ok"), "missing justification rejected")

    banner("spec_cmd: action with justification, allowed motor, action_log written")
    ok = spec_cmd.call(
        "umv", ["m1vert", "1.93"],
        justification="smoke test moving m1vert to mocked nominal",
    )
    assert_true(ok.get("ok") and ok.get("action_id"), "umv m1vert dispatched and logged")

    banner("spec_cmd: action with motor off-allowlist rejected")
    bad2 = spec_cmd.call("umv", ["Ax1", "0"], justification="try illegal")
    assert_true(not bad2.get("ok"), "Ax1 rejected in beamline_alignment phase (XES-only motor)")

    banner("procedural: align_beamline succeeds in mock")
    res = spec_cmd.call("align_beamline", ["0", "0", "0", "0"],
                       justification="run full alignment")
    assert_true(res.get("ok"), "align_beamline ran in mock")
    checker.record("align_beamline_ok", True)
    checker.record("calibrate_mono_residual_ev", 0.05)

    banner("phase gate: sample_alignment requires samples aligned")
    r2 = await transition_phase(exp.id, phase_allowlist.PHASE_SAMPLE_ALIGN,
                                "move to sample alignment", checker)
    assert_true(r2.allowed, "bl_align -> sample_alignment allowed after preconds")

    banner("staff guidance + intervention pause")
    coordinator.record_guidance(
        experiment_id=exp.id, source="test", author="operator",
        text="prioritize sample_b if SNR diverges",
    )
    drained = coordinator.drain_guidance(exp.id)
    assert_true(len(drained) == 1 and drained[0]["author"] == "operator",
                "guidance drained for next turn")

    notify_flag = {"fired": False}
    async def fake_notify(intervention_id: str, detail: str):
        notify_flag["fired"] = True
        # Immediately resolve so the tool unblocks
        await coordinator.resolve(intervention_id, status="resolved", resolver="tester")

    outcome = await coordinator.request_intervention(
        experiment_id=exp.id, kind="sample_mount",
        detail="Install sample holder", timeout_s=10, notify=fake_notify,
    )
    assert_true(notify_flag["fired"], "intervention notifier fired")
    assert_true(outcome["status"] == "resolved", "intervention resolved")

    banner("backward transition denied without approver")
    r_back = await transition_phase(
        exp.id, phase_allowlist.PHASE_BL_ALIGN,
        "try to go back", checker, approval_requester=None,
    )
    assert_true(not r_back.allowed, "backward without channel is denied")

    banner("backward transition approved via stub requester")
    async def approver(kind, detail):
        return {"status": "approved", "resolver": "stub"}
    r_back2 = await transition_phase(
        exp.id, phase_allowlist.PHASE_BL_ALIGN,
        "retry with approver", checker, approval_requester=approver,
    )
    assert_true(r_back2.allowed, "backward with approver succeeds")

    banner("plan update + sample progress")
    plan_dict = get_experiment_plan(exp.id) or {}
    first_sample_id = plan_dict["plan"]["sample_queue"][0]["sample_id"]
    planner.record_sample_progress(
        exp.id, first_sample_id, status="done", snr_estimate=12.3,
        efficiency_verdict="reasonable", reps_completed=3,
    )
    snap2 = planner.snapshot(exp.id)
    assert_true(snap2.samples_completed == 1, "first sample marked done")

    banner("action log visible")
    actions = recent_actions(limit=50, experiment_id=exp.id)
    assert_true(any(a["command"] == "umv" for a in actions), "umv visible in action_log")
    assert_true(any(a["command"] == "align_beamline" for a in actions),
                "align_beamline visible in action_log")
    assert_true(all(a["justification"] for a in actions if a["command"] != "wa"),
                "every action_log row has a justification")

    print("\nALL SMOKE CHECKS PASSED ✓")


if __name__ == "__main__":
    asyncio.run(run())
