"""Plan-validation tests for `replace_plan` / `t_update_plan`.

Goal: prove that during the `collection` phase, the planner cannot
write a plan whose every sample is in a terminal status
(`done`/`skipped`/`failed`) — that state is the deadlock that took
the system deaf in production.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.planner import planner  # noqa: E402
from beamline_tools.tool_catalog import tools  # noqa: E402


@pytest.fixture
def stub_plan_store(monkeypatch):
    """Replace get_plan/upsert_experiment_plan with in-memory stubs.

    Returns a dict with `current_phase` (read by validation) and
    `last_write` (captured if the write was allowed through).
    """
    state = {"current_phase": "collection", "last_write": None}

    def fake_get_plan(experiment_id):
        return {"phase": state["current_phase"]}

    def fake_upsert(experiment_id, *, plan=None, **kw):
        state["last_write"] = plan

    monkeypatch.setattr(planner, "get_plan", fake_get_plan)
    monkeypatch.setattr(planner, "upsert_experiment_plan", fake_upsert)
    return state


def _plan_with_statuses(*statuses: str) -> dict:
    return {
        "sample_queue": [
            {"sample_id": f"s{i}", "status": s} for i, s in enumerate(statuses)
        ],
    }


def test_all_done_during_collection_raises(stub_plan_store):
    plan = _plan_with_statuses("done", "done", "skipped", "failed")
    with pytest.raises(planner.PlanValidationError):
        planner.replace_plan("exp-1", plan)
    assert stub_plan_store["last_write"] is None


def test_at_least_one_in_progress_passes(stub_plan_store):
    plan = _plan_with_statuses("done", "in_progress", "failed")
    planner.replace_plan("exp-1", plan)
    assert stub_plan_store["last_write"] is not None


def test_at_least_one_queued_passes(stub_plan_store):
    plan = _plan_with_statuses("done", "queued", "skipped")
    planner.replace_plan("exp-1", plan)
    assert stub_plan_store["last_write"] is not None


def test_all_done_during_setup_passes(stub_plan_store):
    stub_plan_store["current_phase"] = "setup"
    plan = _plan_with_statuses("done", "done", "done")
    planner.replace_plan("exp-1", plan)
    assert stub_plan_store["last_write"] is not None


def test_all_done_during_complete_passes(stub_plan_store):
    stub_plan_store["current_phase"] = "complete"
    plan = _plan_with_statuses("done", "done", "skipped")
    planner.replace_plan("exp-1", plan)
    assert stub_plan_store["last_write"] is not None


def test_no_current_plan_skips_validation(stub_plan_store, monkeypatch):
    monkeypatch.setattr(planner, "get_plan", lambda _eid: None)
    plan = _plan_with_statuses("done", "done")
    planner.replace_plan("exp-1", plan)
    assert stub_plan_store["last_write"] is not None


def test_empty_sample_queue_during_collection_raises(stub_plan_store):
    plan = {"sample_queue": []}
    with pytest.raises(planner.PlanValidationError):
        planner.replace_plan("exp-1", plan)


def test_t_update_plan_returns_error_envelope(stub_plan_store, monkeypatch):
    monkeypatch.setattr(tools.runtime_state, "get_experiment_id",
                        lambda: "exp-1")
    # Suppress the best-effort plan_summary side-effect; not under test.
    import orchestration.planner.plan_summary as plan_summary_mod
    monkeypatch.setattr(plan_summary_mod, "generate_and_post",
                        lambda _eid: None)

    plan = _plan_with_statuses("done", "skipped", "failed")
    body_json, _ = tools.t_update_plan({"plan": plan})
    body = json.loads(body_json)
    assert body["ok"] is False
    assert "zero actionable samples" in body["error"]


def test_t_update_plan_returns_ok_on_valid_plan(stub_plan_store, monkeypatch):
    monkeypatch.setattr(tools.runtime_state, "get_experiment_id",
                        lambda: "exp-1")
    import orchestration.planner.plan_summary as plan_summary_mod
    monkeypatch.setattr(plan_summary_mod, "generate_and_post",
                        lambda _eid: None)

    plan = _plan_with_statuses("in_progress", "queued")
    body_json, _ = tools.t_update_plan({"plan": plan})
    body = json.loads(body_json)
    assert body["ok"] is True


# ---------------------------------------------------------------------------
# Schema validation (plan_schema.validate_plan_doc via replace_plan)
# ---------------------------------------------------------------------------

def test_replace_plan_normalizes_status_case(stub_plan_store):
    stub_plan_store["current_phase"] = "setup"
    plan = {"sample_queue": [
        {"sample_id": "s1", "status": "Done"},
        {"sample_id": "s2", "status": "IN_PROGRESS"},
    ]}
    planner.replace_plan("exp-1", plan)
    written = stub_plan_store["last_write"]
    assert [s["status"] for s in written["sample_queue"]] == ["done", "in_progress"]


def test_replace_plan_rejects_unknown_status(stub_plan_store):
    plan = {"sample_queue": [{"sample_id": "s1", "status": "paused"}]}
    with pytest.raises(planner.PlanValidationError) as exc:
        planner.replace_plan("exp-1", plan)
    assert "status" in str(exc.value)
    assert stub_plan_store["last_write"] is None


def test_replace_plan_rejects_missing_sample_id(stub_plan_store):
    plan = {"sample_queue": [{"status": "queued"}]}
    with pytest.raises(planner.PlanValidationError) as exc:
        planner.replace_plan("exp-1", plan)
    assert "sample_id" in str(exc.value)


def test_replace_plan_rejects_negative_reps(stub_plan_store):
    plan = {"sample_queue": [{"sample_id": "s1", "status": "queued",
                              "reps_completed": -2}]}
    with pytest.raises(planner.PlanValidationError):
        planner.replace_plan("exp-1", plan)


def test_replace_plan_preserves_agent_extra_fields(stub_plan_store):
    stub_plan_store["current_phase"] = "setup"
    plan = {
        "sample_queue": [{"sample_id": "s1", "status": "queued",
                          "agent_note": "watch for damage"}],
        "agent_strategy": "fresh spots every 2 reps",
    }
    planner.replace_plan("exp-1", plan)
    written = stub_plan_store["last_write"]
    assert written["agent_strategy"] == "fresh spots every 2 reps"
    assert written["sample_queue"][0]["agent_note"] == "watch for damage"


def test_replace_plan_fills_entry_defaults(stub_plan_store):
    stub_plan_store["current_phase"] = "setup"
    plan = {"sample_queue": [{"sample_id": "s1"}]}
    planner.replace_plan("exp-1", plan)
    entry = stub_plan_store["last_write"]["sample_queue"][0]
    assert entry["status"] == "queued"
    assert entry["reps_completed"] == 0
    assert entry["modes"] == []


def test_t_update_plan_surfaces_schema_error_to_agent(stub_plan_store, monkeypatch):
    monkeypatch.setattr(tools.runtime_state, "get_experiment_id",
                        lambda: "exp-1")
    plan = {"sample_queue": [{"sample_id": "s1", "status": "completed"}]}
    body_json, _ = tools.t_update_plan({"plan": plan})
    body = json.loads(body_json)
    assert body["ok"] is False
    assert "queued" in body["error"]  # lists the valid statuses
