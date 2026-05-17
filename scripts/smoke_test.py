"""End-to-end smoke test for the autonomous beamline agent.

Runs in SPEC_MOCK mode (no real SPEC required). Walks through: phase
state (runtime_state + ExperimentPlan write-through), audited_call
dispatch with action_log writes, staff guidance + intervention
resolution, plan/budget tracking.

Run from the repo root:

    PYTHONPATH=server SPEC_MOCK=1 AUTONOMOUS_DB_PATH=data/smoke.db \
        python scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
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

# Flip the SPEC-write safety switch on for the duration of this run, then
# restore. The committed default is `spec_write_enabled: false` (deploy
# safety); the smoke test needs writes for its mock round-trip.
import atexit  # noqa: E402
import json  # noqa: E402
_SAFETY = ROOT / "beamline_tools" / "safety_switches.json"
_ORIG_SAFETY = _SAFETY.read_text() if _SAFETY.exists() else None
if _ORIG_SAFETY is not None:
    _SAFETY.write_text(json.dumps(
        {"spec_read_enabled": True, "spec_write_enabled": True},
        indent=2,
    ) + "\n")

    def _restore_safety_switches() -> None:
        try:
            _SAFETY.write_text(_ORIG_SAFETY)
        except Exception:
            pass

    atexit.register(_restore_safety_switches)

from orchestration import runtime_state  # noqa: E402
from orchestration.plan_store import init_db  # noqa: E402
from orchestration.plan_store.session import (  # noqa: E402
    create_experiment,
    create_experiment_element,
    create_sample_holder,
    create_sample_position,
)
from orchestration.plan_store.client import (  # noqa: E402
    get_plan,
)
from orchestration.planner import planner  # noqa: E402
from orchestration.planner.staff_guidance import coordinator  # noqa: E402
from beamline_tools.audited_call import audited_call  # noqa: E402
from beamline_tools.spec_control import phases  # noqa: E402
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
        n_crystals=3, vortex_counter="vortDT", priority=0,
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
    runtime_state.set_phase(phases.PHASE_SETUP, experiment_id=exp.id)
    assert_true(runtime_state.get_experiment_id() == exp.id, "runtime_state tracks experiment id")

    banner("build plan")
    planner.build_initial_plan(exp.id, beamtime_hours=6.0)
    # End-time is now the budget source-of-truth: set 6h from now and
    # confirm the snapshot derives ~6 remaining.
    from datetime import datetime as _dt, timedelta as _td
    from orchestration.plan_store.session import set_experiment_end_time
    set_experiment_end_time(exp.id, _dt.now() + _td(hours=6))
    snap = planner.snapshot(exp.id)
    assert_true(snap.samples_total == 2, "two samples in plan")
    assert_true(
        5.9 <= snap.beamtime_remaining_hours <= 6.0,
        f"end_time-driven remaining ≈ 6h (got {snap.beamtime_remaining_hours:.3f})",
    )

    banner("phase: set_phase writes through to ExperimentPlan.phase")
    runtime_state.set_phase(phases.PHASE_BL_ALIGN, experiment_id=exp.id)
    assert_true(
        runtime_state.get_phase() == phases.PHASE_BL_ALIGN,
        "in-memory phase updated",
    )
    persisted = get_plan(exp.id) or {}
    assert_true(
        persisted.get("phase") == phases.PHASE_BL_ALIGN,
        "ExperimentPlan.phase write-through",
    )

    banner("audited_call: read (wa)")
    w = audited_call("wa", [], justification="")
    assert_true(w.get("ok") and "positions" in w["result"], "wa returned parsed positions")

    banner("audited_call: action without justification rejected")
    bad = audited_call("umv", ["m1vert", "1.93"], justification="")
    assert_true(not bad.get("ok"), "missing justification rejected")

    banner("audited_call: action with justification, action_log written")
    ok = audited_call(
        "umv", ["m1vert", "1.93"],
        justification="smoke test moving m1vert to mocked nominal",
    )
    assert_true(ok.get("ok") and ok.get("action_id"), "umv m1vert dispatched and logged")

    # Motor/role allowlist enforcement lives at the CLI layer
    # (scripts/beamtimehero per-role argparse branch), not in audited_call.
    # See scripts/unit_test_spec_tools.py or the CLI integration tests
    # for per-role motor rejection coverage.

    banner("procedural: align_beamline succeeds in mock")
    res = audited_call("align_beamline", ["0", "0", "0", "0"],
                       justification="run full alignment")
    assert_true(res.get("ok"), "align_beamline ran in mock")

    banner("phase: advance to sample_alignment (plain setter, no gating)")
    runtime_state.set_phase(phases.PHASE_SAMPLE_ALIGN, experiment_id=exp.id)
    assert_true(
        runtime_state.get_phase() == phases.PHASE_SAMPLE_ALIGN,
        "phase advanced",
    )

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

    banner("phase: unknown slug is rejected")
    try:
        runtime_state.set_phase("not-a-real-phase", experiment_id=exp.id)
        rejected = False
    except ValueError:
        rejected = True
    assert_true(rejected, "set_phase('not-a-real-phase') raises ValueError")

    banner("plan update + sample progress")
    plan_dict = get_plan(exp.id) or {}
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
