"""Tests for the observable-degradation tracking feature.

Covers the persistence half of "watch whether the observable we're after is
degrading": the `record_observable_trend` mutator, the plan-schema fields it
writes (`observable_trend`, `thresholds.max_drift_ev`), and the plan-summary
drift alert that surfaces a degrading sample to staff.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.planner import planner  # noqa: E402
from orchestration.planner import plan_summary  # noqa: E402
from orchestration.planner.plan_schema import validate_plan_doc  # noqa: E402


@pytest.fixture
def stub_plan_store(monkeypatch):
    """In-memory plan store seeded with a two-sample queue.

    `record_observable_trend` goes through `_mutate_plan`, which reads
    get_plan()['plan'] and writes via upsert_experiment_plan. The stub
    captures the written body in state['last_write'].
    """
    state = {
        "plan": {
            "sample_queue": [
                {"sample_id": "s0", "status": "done"},
                {"sample_id": "s1", "status": "in_progress"},
            ],
        },
        "last_write": None,
    }

    def fake_get_plan(experiment_id):
        return {"version": 0, "phase": "collection", "plan": state["plan"]}

    def fake_upsert(experiment_id, *, plan=None, **kw):
        state["last_write"] = plan

    monkeypatch.setattr(planner, "get_plan", fake_get_plan)
    monkeypatch.setattr(planner, "upsert_experiment_plan", fake_upsert)
    return state


def test_record_observable_trend_writes_field(stub_plan_store):
    trend = {
        "metric": "e0_ev",
        "theil_slope_per_scan": -0.22,
        "kendall_tau": -0.9,
        "direction": "reduction",
        "drift_detected": True,
        "verdict": "drifting-reduction",
        "n_scans_assessed": 6,
    }
    planner.record_observable_trend("exp-1", "s1", trend)
    written = stub_plan_store["last_write"]
    assert written is not None
    s1 = next(s for s in written["sample_queue"] if s["sample_id"] == "s1")
    assert s1["observable_trend"]["direction"] == "reduction"
    assert s1["observable_trend"]["drift_detected"] is True


def test_record_observable_trend_leaves_other_samples_untouched(stub_plan_store):
    planner.record_observable_trend("exp-1", "s1", {"drift_detected": False})
    written = stub_plan_store["last_write"]
    s0 = next(s for s in written["sample_queue"] if s["sample_id"] == "s0")
    assert s0.get("observable_trend") is None


def test_schema_accepts_observable_trend_and_max_drift_ev():
    doc = validate_plan_doc({
        "sample_queue": [{
            "sample_id": "s1", "status": "in_progress",
            "observable_trend": {"metric": "e0_ev", "drift_detected": True,
                                 "values": [7112.0, 7111.9, 7111.7]},
        }],
        "thresholds": {"snr_target": 8.0, "min_reps_per_sample": 3,
                       "max_drift_ev": 0.15},
    })
    assert doc["thresholds"]["max_drift_ev"] == 0.15
    entry = doc["sample_queue"][0]
    assert entry["observable_trend"]["drift_detected"] is True
    # per-rep trajectory (the operando deliverable) survives the round-trip
    assert entry["observable_trend"]["values"] == [7112.0, 7111.9, 7111.7]


def test_max_drift_ev_rejects_nonpositive():
    from orchestration.planner.plan_schema import PlanSchemaError
    with pytest.raises(PlanSchemaError):
        validate_plan_doc({
            "sample_queue": [{"sample_id": "s1", "status": "queued"}],
            "thresholds": {"max_drift_ev": 0},
        })


# ---------------------------------------------------------------------------
# plan_summary drift alert
# ---------------------------------------------------------------------------

def test_format_drift_alerts_on_drift():
    line = plan_summary._format_drift({
        "metric": "e0_ev", "theil_slope_per_scan": -0.22, "direction": "reduction",
        "drift_detected": True,
    })
    assert line is not None
    assert "drift" in line and "e0_ev" in line and "reduction" in line
    assert "-0.22" in line


def test_format_drift_none_when_stable():
    assert plan_summary._format_drift({"drift_detected": False}) is None


def test_format_drift_none_when_absent():
    assert plan_summary._format_drift(None) is None
